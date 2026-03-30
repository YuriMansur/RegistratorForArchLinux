"""
UsbExporter — синхронизация session exports на USB-флешку.
Вызывается при вставке/извлечении флешки через usb_monitor.

Логика:
  - При вставке: монтируем, сравниваем с EXPORT_DIR, копируем только отсутствующие файлы.
  - При извлечении: размонтируем /mnt/usb.
"""
import shutil
import subprocess
import threading
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

EXPORT_DIR   = Path("/home/user/registrator/exports")
USB_SUBDIR   = ""  # файлы пишутся в корень флешки
_MOUNT_POINT = "/mnt/usb"

# "idle" | "waiting" | "writing" | "done" | "error"
_status: str = "idle"
_current_partition: str | None = None
_lock = threading.Lock()


def get_status() -> str:
    return _status


def _set_status(s: str):
    global _status
    _status = s


# ── Поиск раздела ─────────────────────────────────────────────────────────────

def _get_partition(disk_node: str, timeout: float = 5.0) -> str | None:
    """Ждём появления первого раздела диска (например /dev/sdb → /dev/sdb1)."""
    import os
    disk_name = disk_node.replace("/dev/", "")
    deadline = time.time() + timeout
    while time.time() < deadline:
        sys_path = f"/sys/block/{disk_name}"
        try:
            for entry in os.listdir(sys_path):
                if entry.startswith(disk_name):
                    return f"/dev/{entry}"
        except OSError:
            pass
        time.sleep(0.3)
    return None


# ── Монтирование ──────────────────────────────────────────────────────────────

def _find_mount_point(device: str) -> str | None:
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == device:
                    return parts[1]
    except OSError:
        pass
    return None


def _unmount_if_busy():
    """Размонтировать /mnt/usb если там что-то уже смонтировано."""
    for _ in range(10):
        try:
            with open("/proc/mounts") as f:
                mounted = any(_MOUNT_POINT in line for line in f)
        except OSError:
            break
        if not mounted:
            break
        subprocess.run(
            ["sudo", "umount", _MOUNT_POINT],
            capture_output=True, timeout=5,
        )


def _mount_partition(partition: str) -> str | None:
    mount_point = _find_mount_point(partition)
    if mount_point:
        return mount_point
    _unmount_if_busy()
    try:
        import os
        os.makedirs(_MOUNT_POINT, exist_ok=True)
        result = subprocess.run(
            ["sudo", "mount", "-o", "uid=1000,gid=1000,umask=002", partition, _MOUNT_POINT],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            # Для Linux-FS (ext4 и т.п.) опции uid/gid не поддерживаются
            result = subprocess.run(
                ["sudo", "mount", partition, _MOUNT_POINT],
                capture_output=True, text=True, timeout=10,
            )
        if result.returncode == 0:
            return _MOUNT_POINT
        log.error("mount failed: %s", result.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.error("mount exception: %s", e)
    return None


# ── Пищалка ───────────────────────────────────────────────────────────────────

def _beep(freq: int, duration_ms: int):
    try:
        subprocess.Popen(
            ["beep", "-f", str(freq), "-l", str(duration_ms)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def _build_melody_cmd() -> list[str]:
    """Строит команду beep для мелодии Super Mario Bros (Overworld Theme).
    200 BPM: четверть = 300ms, восьмая = 150ms, пунктирная четверть = 450ms.
    Формат нот: (частота_Гц, длительность_мс, пауза_после_мс). 0 Гц = пауза.
    """
    E4  = 330
    G4  = 392
    A4  = 440
    Bb4 = 466
    B4  = 494
    C5  = 523
    D5  = 587
    E5  = 659
    F5  = 698
    G5  = 784
    A5  = 880

    q  = 300   # четверть
    e  = 150   # восьмая
    dq = 450   # пунктирная четверть (q + e)

    notes = [
        # Интро-риф
        (E5,e,e), (E5,e,e), (E5,e,0), (C5,e,0), (E5,q,0),
        (G5,q,q), (G4,q,0),
        # Основная мелодия — строка 1
        (C5,dq,0), (G4,e,q), (E4,dq,0),
        (A4,q,0), (B4,q,0), (Bb4,e,0), (A4,q,0),
        # Строка 2
        (G4,e,0), (E5,e,0), (G5,e,0), (A5,q,0),
        (F5,e,0), (G5,e,0), (E5,q,0),
        (C5,e,0), (D5,e,0), (B4,dq,0),
    ]

    args = ["beep"]
    for freq, dur, delay in notes:
        if freq == 0:
            # пауза — добавляем задержку к предыдущей ноте
            if len(args) > 1:
                args += ["-D", str(dur)]
            continue
        if len(args) > 1:
            args.append("-n")
        args += ["-f", str(freq), "-l", str(dur)]
        if delay > 0:
            args += ["-D", str(delay)]
    return args


def _beep_worker(stop_event: threading.Event):
    """Играет Super Mario в цикле пока stop_event не установлен."""
    cmd = _build_melody_cmd()
    while not stop_event.is_set():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            while not stop_event.is_set() and proc.poll() is None:
                time.sleep(0.05)
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
        except FileNotFoundError:
            break


# ── Синхронизация файлов ──────────────────────────────────────────────────────

def _dir_matches_usb(src_dir: Path, usb_dir: Path) -> bool:
    """Все файлы из src_dir есть на USB с тем же именем и размером."""
    for src_file in src_dir.iterdir():
        if not src_file.is_file():
            continue
        dst_file = usb_dir / src_dir.name / src_file.name
        if not dst_file.exists():
            return False
        if dst_file.stat().st_size != src_file.stat().st_size:
            return False
    return True


def _get_missing_dirs(usb_dir: Path) -> list[Path]:
    """Папки checkout_* из EXPORT_DIR, которых нет на USB или файлы не совпадают по размеру."""
    if not EXPORT_DIR.exists():
        log.warning("EXPORT_DIR not found: %s", EXPORT_DIR)
        return []

    export_dirs = sorted(d for d in EXPORT_DIR.iterdir() if d.is_dir() and d.name.startswith("checkout_"))
    log.info("EXPORT_DIR has %d checkout dir(s)", len(export_dirs))

    missing = [d for d in export_dirs if not _dir_matches_usb(d, usb_dir)]
    log.info("Dirs to copy (missing or changed): %d", len(missing))
    return missing


def _verify_dir(src: Path, dst: Path) -> None:
    """Проверить все файлы в папке: существуют, не пустые, размеры совпадают."""
    for src_file in src.iterdir():
        if not src_file.is_file():
            continue
        dst_file = dst / src_file.name
        if not dst_file.exists():
            raise RuntimeError(f"File missing after copy: {dst_file.name}")
        if dst_file.stat().st_size == 0:
            raise RuntimeError(f"File empty after copy: {dst_file.name}")
        if dst_file.stat().st_size != src_file.stat().st_size:
            raise RuntimeError(
                f"Size mismatch {src_file.name}: src={src_file.stat().st_size}, dst={dst_file.stat().st_size}"
            )


# ── Основная логика экспорта ──────────────────────────────────────────────────

def _do_export(device_info: dict):
    global _current_partition
    node = device_info.get("node", "")
    log.info("USB inserted: looking for partition on %s...", node)
    _set_status("waiting")

    partition = _get_partition(node)
    if not partition:
        log.error("No partition found on %s — export skipped", node)
        _set_status("error")
        return

    log.info("Found partition: %s, mounting...", partition)
    mount_point = _mount_partition(partition)
    if not mount_point:
        log.error("Could not mount %s — export skipped", partition)
        _set_status("error")
        return

    with _lock:
        _current_partition = partition

    # Корень флешки
    usb_dir = Path(mount_point)

    # Определяем какие папки нужно скопировать
    missing = _get_missing_dirs(usb_dir)
    if not missing:
        log.info("USB: all checkout dirs already present, nothing to copy")
        _set_status("done")
        _beep(1000, 400)
        return

    log.info("Copying %d checkout dir(s) to USB", len(missing))
    _set_status("writing")

    stop_beep = threading.Event()
    beep_thread = threading.Thread(target=_beep_worker, args=(stop_beep,), daemon=True)
    beep_thread.start()

    try:
        # Этап 1: копирование
        for src_dir in missing:
            dst_dir = usb_dir / src_dir.name
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            log.info("Copied dir: %s", src_dir.name)

        # Сброс буферов на диск перед верификацией
        import os
        os.sync()

        # Этап 2: проверка всех скопированных папок и файлов
        for src_dir in missing:
            dst_dir = usb_dir / src_dir.name
            _verify_dir(src_dir, dst_dir)
            log.info("Verified dir: %s", src_dir.name)

        _set_status("done")
        log.info("USB export done: %d dir(s) copied and verified", len(missing))
    except Exception:
        log.exception("USB export failed")
        _set_status("error")
    finally:
        stop_beep.set()
        beep_thread.join(timeout=1.0)
        if _status == "done":
            _beep(1000, 400)
        log.info("USB drive stays mounted until physically removed")


# ── Публичный API ─────────────────────────────────────────────────────────────

def export_on_insert(device_info: dict):
    """Точка входа при вставке — запускает экспорт в фоновом потоке."""
    threading.Thread(
        target=_do_export,
        args=(device_info,),
        daemon=True,
        name="usb-export",
    ).start()


def on_usb_removed(_device_info: dict):
    """Точка входа при извлечении — размонтируем /mnt/usb."""
    global _current_partition
    with _lock:
        partition = _current_partition
    if partition:
        log.info("USB removed (%s), unmounting %s...", partition, _MOUNT_POINT)
        _unmount_if_busy()
        with _lock:
            _current_partition = None
        log.info("Unmounted %s", _MOUNT_POINT)
    _set_status("idle")
