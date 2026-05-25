# paramiko — SSH/SFTP-клиент для заливки файлов и выполнения команд на сервере.
import paramiko
# os — для раскрытия пути к SSH-ключу через ~.
import os

from pathlib import Path

# Ключ по-умолчанию для подключения к серверу (можно заменить на другой, если нужно).
key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))
# Установка SSH-соединения с сервером.
ssh = paramiko.SSHClient()
# Разрешить добавление нового хоста в known_hosts.
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# Подключение к удалённому серверу: указываем пользователя и приватный ключ.
ssh.connect("192.168.10.222", username="user", pkey=key)
# Открытие SFTP-сессии для передачи файлов поверх существующего SSH.
sftp = ssh.open_sftp()

# Локальная папка с серверным кодом.
# .resolve() обязательно — иначе при запуске через bat (где путь может содержать `..\`)
# pathlib не нормализует и .parent.parent даст scripts\bat\ вместо корня проекта.
SCRIPT = Path(__file__).resolve()
server_dir = SCRIPT.parent.parent / "server"
# Корневая папка деплоя на удалённой машине. Сохраняем структуру server/* внутри.
REMOTE_ROOT = "/home/user/registrator/server"

# ── Очистка устаревшего на сервере ────────────────────────────────────────────
# 1) Сносим __pycache__ — старые .pyc могут указывать на удалённые модули (например opcua_tags).
# 2) Удаляем opcua_tags.py — выпилен локально, через SFTP он бы остался висеть мусором.
print("Cleaning up stale files on server...")
ssh.exec_command("find /home/user/registrator -type d -name __pycache__ -exec rm -rf {} +")[1].read()
ssh.exec_command("rm -f /home/user/registrator/server/protocol_backend/protocol_client/opcua_tags.py")[1].read()
print("ok cleanup")

# ── Заливка файлов из server/ ─────────────────────────────────────────────────
# Проходим по всем файлам рекурсивно и грузим на сервер, сохраняя относительную структуру.
for f in server_dir.rglob("*"):
    # Папки не льём — sftp.put требует файл; нужные папки создадим mkdir -p ниже.
    if f.is_dir():
        continue
    # Относительный путь от server_dir — критично: f сам по себе абсолютный
    # (особенно при запуске через .bat), и as_posix() без relative_to даёт что-то вида
    # "C:/Users/.../server/main.py", что собрало бы битый remote путь с двоеточием.
    rel = f.relative_to(server_dir).as_posix()
    # Отсекаем кэши Python, локальные venv и БД — не должны попадать на сервер.
    if "__pycache__" in rel or ".venv" in rel or rel.endswith(".db"):
        continue
    # Полный путь на сервере = корень деплоя + относительный путь.
    remote = f"{REMOTE_ROOT}/{rel}"
    # Папка контейнер для файла — может ещё не существовать на сервере.
    remote_dir = remote.rsplit("/", 1)[0]
    # mkdir -p создаёт всю цепочку папок (если уже есть — не ошибка).
    ssh.exec_command(f"mkdir -p {remote_dir}")[1].read()
    # Заливаем файл по SFTP.
    sftp.put(str(f), remote)
    # Лог: какие именно файлы ушли — удобно для проверки в консоли.
    print("ok", rel)

# Деплоим backup_system.sh — лежит рядом со скриптом в scripts/.
# Используем нормализованный SCRIPT (см. выше) — иначе при запуске из bat путь будет битым.
sftp.put(str(SCRIPT.parent / "backup_system.sh"), "/home/user/backup_system.sh")
ssh.exec_command("chmod +x /home/user/backup_system.sh")[1].read()
print("ok backup_system.sh")

# Закрытие SFTP-сессии — больше файлов не грузим.
sftp.close()
print("all done")

# ── Опциональный перезапуск сервиса ───────────────────────────────────────────

# Спрашиваем у пользователя — иногда нужно сначала посмотреть результат до рестарта.
answer = input("\nПерезапустить registrator.service? [y/N]: ").strip().lower()

if answer == "y":
    print("Перезапускаю registrator.service...")
    # echo 1111 | sudo -S — передаём пароль на stdin, чтобы sudo не запросил его интерактивно.
    _, out, err = ssh.exec_command("echo 1111 | sudo -S systemctl restart registrator")
    # Ждём завершения команды (чтение полного stdout/stderr).
    out.read()
    err.read()
    print("Готово. Проверяю статус...")
    # is-active возвращает "active" / "failed" / "inactive" — короткий статус сервиса.
    _, out, _ = ssh.exec_command("systemctl is-active registrator")
    status = out.read().decode().strip()
    print(f"Статус: {status}")
else:
    print("Перезапуск пропущен.")

# Закрытие SSH-соединения.
ssh.close()
