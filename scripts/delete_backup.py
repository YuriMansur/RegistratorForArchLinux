# Удаление бэкапа на сервере по SSH с выбором типа:
#   1) системный бэкап (.fsa в /home/user/system_backups) — принадлежит root, rm через sudo;
#   2) бэкап БД (.db в /home/user/registrator_backups)     — принадлежит user, rm без sudo.
# Скрипт показывает список доступных бэкапов выбранного типа (новые сверху, с размером),
# просит выбрать один и подтвердить, затем удаляет его.

# paramiko — SSH-клиент (как в download_backup.py / trigger_backup.py).
import paramiko
# os — раскрытие ~ в пути к ключу.
import os
# sys — код возврата для .bat/автоматизации.
import sys

# ── Параметры подключения ──────────────────────────────────────────────────────
# IP сервера в локальной сети стенда.
HOST = "192.168.10.222"
# Системный пользователь на сервере.
USER = "user"
# Приватный SSH-ключ.
KEY_PATH = "~/.ssh/registrator_key"
# Пароль sudo — нужен только для удаления системных бэкапов (root-owned).
SUDO_PASS = "1111"

# ── Типы бэкапов ────────────────────────────────────────────────────────────────
# Ключ выбора → (название, папка на сервере, glob-маска, нужен ли sudo для rm).
TYPES = {
    "1": ("Системный бэкап (.fsa)", "/home/user/system_backups",    "*.fsa", True),
    "2": ("Бэкап БД (.db)",         "/home/user/registrator_backups", "*",   False),
}


def run(ssh, cmd: str) -> tuple[str, str]:
    """Выполнить команду на сервере, вернуть (stdout, stderr) как строки."""
    _, out, err = ssh.exec_command(cmd)
    return out.read().decode(errors="replace"), err.read().decode(errors="replace")


def main() -> int:
    # ── Выбор типа бэкапа ───────────────────────────────────────────────────────
    print("Что удаляем?")
    for k, (name, _dir, _pat, _sudo) in TYPES.items():
        print(f"  [{k}] {name}")
    choice = input("Выберите тип [1/2]: ").strip()
    if choice not in TYPES:
        print(f"Ошибка: нет типа '{choice}'.")
        return 1
    name, directory, pattern, need_sudo = TYPES[choice]

    # ── Подключение ─────────────────────────────────────────────────────────────
    key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser(KEY_PATH))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, pkey=key)

    try:
        # ── Список бэкапов выбранного типа (новые сверху) ───────────────────────
        # ls -t — сортировка по времени; 2>/dev/null — молча, если файлов нет.
        out, _ = run(ssh, f"ls -t {directory}/{pattern} 2>/dev/null")
        files = [line.strip() for line in out.splitlines() if line.strip()]
        if not files:
            print(f"\nНет бэкапов типа «{name}» в {directory}.")
            return 1

        # Размеры одним вызовом du — собираем в dict path→size для красивого вывода.
        quoted = " ".join(f"'{f}'" for f in files)
        du_out, _ = run(ssh, f"du -h {quoted} 2>/dev/null")
        sizes = {}
        for line in du_out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                sizes[parts[1].strip()] = parts[0].strip()

        print(f"\nДоступные бэкапы «{name}» (новые сверху):")
        for i, f in enumerate(files):
            print(f"  [{i}] {sizes.get(f, '?'):>6}  {f}")

        # ── Выбор файла ─────────────────────────────────────────────────────────
        idx_raw = input(f"\nНомер для удаления [0..{len(files) - 1}]: ").strip()
        try:
            idx = int(idx_raw)
        except ValueError:
            print(f"Ошибка: '{idx_raw}' не число.")
            return 1
        if idx < 0 or idx >= len(files):
            print(f"Ошибка: номер должен быть от 0 до {len(files) - 1}.")
            return 1
        target = files[idx]

        # ── Подтверждение ───────────────────────────────────────────────────────
        confirm = input(f"Удалить безвозвратно «{target}»? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Отменено.")
            return 0

        # ── Удаление ────────────────────────────────────────────────────────────
        # Системные .fsa принадлежат root → rm через sudo (пароль на stdin, -p '' без приглашения).
        # Бэкапы БД принадлежат user → обычный rm.
        if need_sudo:
            rm_cmd = f"echo {SUDO_PASS} | sudo -S -p '' rm -f -- '{target}'"
        else:
            rm_cmd = f"rm -f -- '{target}'"
        _, err = run(ssh, rm_cmd)

        # Проверяем, что файл действительно исчез.
        check, _ = run(ssh, f"test -e '{target}' && echo exists || echo gone")
        if check.strip() == "gone":
            print(f"Удалено: {target}")
            return 0
        else:
            print(f"Не удалось удалить: {target}")
            if err.strip():
                print(err.strip())
            return 1
    finally:
        ssh.close()


if __name__ == "__main__":
    sys.exit(main())
