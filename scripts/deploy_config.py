"""
deploy_config.py — заливка только server/config/*.json на сервер, без всего кода.

Используется когда нужно подправить теги (servers.json) или подписи (signals.json)
без полного передеплоя. Существенно быстрее deploy_helper.py.

В конце спрашивает про рестарт registrator.service — без него servers.json не подхватится
(client_manager.py читает конфиг при импорте), signals.json подхватится через 60с
на клиенте сам, но на сервере (session_exporter) — тоже при импорте.
"""
# paramiko — SSH/SFTP-клиент.
import paramiko
# os — для раскрытия пути к SSH-ключу через ~.
import os
# sys — для чтения CLI-аргументов (опциональный override директории).
import sys
# Path — работа с путями относительно расположения скрипта.
from pathlib import Path

# Удалённая папка конфигов — фиксированная, должна совпадать со структурой деплоя.
# При смене папки на сервере поменять здесь.
REMOTE_DIR = "/home/user/registrator/server/config"

# Ed25519-ключ для аутентификации на сервере.
key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))
# Установка SSH-клиента.
ssh = paramiko.SSHClient()
# AutoAddPolicy — автоматически принимать ключ хоста (известная сеть).
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# Подключение к серверу.
ssh.connect("192.168.10.222", username="user", pkey=key)
# Открываем SFTP-сессию для заливки файлов.
sftp = ssh.open_sftp()

# .resolve() — нормализуем путь от .bat (может содержать ..\), иначе parent.parent
# даст не то что надо. Аналогично deploy_helper.py.
SCRIPT = Path(__file__).resolve()
# Корень проекта (родитель scripts/).
ROOT = SCRIPT.parent.parent

# ── Выбор локальной папки-источника ──────────────────────────────────────────
# Приоритет: CLI-аргумент > интерактивный выбор из списка > дефолт server/config.
# CLI:
#     python deploy_config.py configs/_170

# Собираем кандидаты: дефолтный server/config + всё что есть в configs/*.
candidates: list[Path] = []
default_source = ROOT / "server" / "config"
if default_source.is_dir():
    candidates.append(default_source)
configs_root = ROOT / "configs"
if configs_root.is_dir():
    candidates.extend(sorted(p for p in configs_root.iterdir() if p.is_dir()))

if len(sys.argv) >= 2 and sys.argv[1].strip():
    # CLI: путь может быть относительным (от корня проекта) или абсолютным.
    raw = sys.argv[1].strip()
    config_dir = Path(raw)
    if not config_dir.is_absolute():
        config_dir = ROOT / raw
    config_dir = config_dir.resolve()
    print(f"Источник из аргумента: {config_dir}")
else:
    # Интерактивный выбор: показываем все варианты + Enter принимает первый (дефолт).
    print("Откуда брать конфиги:")
    for i, p in enumerate(candidates):
        # Показываем путь относительно корня — короче и читаемее.
        try:
            shown = p.relative_to(ROOT).as_posix()
        except ValueError:
            shown = str(p)
        marker = " (по умолчанию)" if i == 0 else ""
        print(f"  [{i}] {shown}{marker}")
    choice = input("Номер варианта (Enter = 0): ").strip()
    idx = int(choice) if choice else 0
    if idx < 0 or idx >= len(candidates):
        print(f"Ошибка: номер должен быть от 0 до {len(candidates) - 1}.")
        ssh.close()
        sys.exit(1)
    config_dir = candidates[idx]
    print(f"Источник: {config_dir}")

if not config_dir.is_dir():
    print(f"Ошибка: папка {config_dir} не существует.")
    ssh.close()
    sys.exit(1)

print(f"Льём в {REMOTE_DIR}")

# Гарантируем что папка существует на сервере (mkdir -p — идемпотентно).
ssh.exec_command(f"mkdir -p {REMOTE_DIR}")[1].read()

# Перебираем все .json файлы из локального config/ и заливаем по SFTP.
deployed = 0
for f in sorted(config_dir.glob("*.json")):
    remote = f"{REMOTE_DIR}/{f.name}"
    # sftp.put перезаписывает целевой файл, не нужно явно удалять старый.
    sftp.put(str(f), remote)
    print(f"ok {f.name}")
    deployed += 1

if deployed == 0:
    print("Нет .json файлов в server/config/ — нечего заливать.")

# Закрываем SFTP — больше файлов не шлём.
sftp.close()
print(f"\n{deployed} файл(ов) задеплоено.")

# ── Опциональный перезапуск сервиса ───────────────────────────────────────────

# Спрашиваем у пользователя — для signals.json часто перезапуск не нужен (клиент
# подтянет за 60с), для servers.json — нужен, иначе изменения опроса не вступят в силу.
answer = input("\nПерезапустить registrator.service? [y/N]: ").strip().lower()

if answer == "y":
    print("Перезапускаю registrator.service...")
    # echo 1111 | sudo -S — пароль на stdin чтобы sudo не блокировался.
    _, out, err = ssh.exec_command("echo 1111 | sudo -S systemctl restart registrator")
    out.read()
    err.read()
    print("Готово. Проверяю статус...")
    # is-active возвращает active/failed/inactive — короткий статус.
    _, out, _ = ssh.exec_command("systemctl is-active registrator")
    status = out.read().decode().strip()
    print(f"Статус: {status}")
else:
    print("Перезапуск пропущен.")

# Закрываем SSH-соединение.
ssh.close()
