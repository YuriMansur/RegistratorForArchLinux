# Запуск системного бэкапа (backup_system.sh) на сервере по SSH.
# Сам backup_system.sh требует root (fsarchiver читает сырые разделы /dev/sda*),
# поэтому дёргаем его через sudo. Вывод fsarchiver стримим в реальном времени —
# бэкап идёт долго, и хочется видеть прогресс, а не молчание до конца.

# paramiko — SSH-клиент (тот же, что в download_backup.py / deploy_helper.py).
import paramiko
# os — для раскрытия ~ в пути к ключу.
import os
# sys — для кода возврата, чтобы .bat/CI понимали успех/провал.
import sys

# ── Параметры подключения (как в остальных скриптах scripts/) ──────────────────
# IP сервера-регистратора в локальной сети стенда.
HOST = "192.168.10.222"
# Системный пользователь на сервере.
USER = "user"
# Приватный SSH-ключ для беспарольного входа.
KEY_PATH = "~/.ssh/registrator_key"
# Пароль sudo — нужен, т.к. fsarchiver требует root. Передаётся sudo на stdin.
SUDO_PASS = "1111"
# Куда deploy_helper.py заливает backup_system.sh на сервере.
REMOTE_SCRIPT = "/home/user/backup_system.sh"


def main() -> int:
    # Загружаем приватный ключ Ed25519 (формат как у registrator_key).
    key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser(KEY_PATH))
    # Создаём SSH-клиент и разрешаем авто-добавление хоста в known_hosts.
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # Подключаемся к серверу по ключу.
    ssh.connect(HOST, username=USER, pkey=key)

    try:
        # Проверяем, что скрипт вообще залит на сервер — иначе понятная ошибка,
        # а не «No such file» из глубины sudo.
        _, out, _ = ssh.exec_command(f"test -f {REMOTE_SCRIPT} && echo yes || echo no")
        if out.read().decode().strip() != "yes":
            print(f"Ошибка: {REMOTE_SCRIPT} не найден на сервере.")
            print("Сначала задеплойте его (scripts/deploy_helper.py заливает backup_system.sh).")
            return 1

        print(f"Запускаю системный бэкап на {HOST}: {REMOTE_SCRIPT}")
        print("(fsarchiver может идти несколько минут — вывод ниже в реальном времени)\n")

        # echo <pass> | sudo -S -p '' — пароль на stdin, -p '' убирает текст приглашения sudo.
        # bash REMOTE_SCRIPT — запускаем сам скрипт бэкапа от root.
        cmd = f"echo {SUDO_PASS} | sudo -S -p '' bash {REMOTE_SCRIPT}"
        _, stdout, stderr = ssh.exec_command(cmd)

        # Стримим stdout построчно, пока канал не закроется — это и есть «живой» прогресс.
        for line in iter(stdout.readline, ""):
            print(line, end="", flush=True)

        # Код возврата самого backup_system.sh: 0 — успех, 1 — бэкап не создан.
        exit_status = stdout.channel.recv_exit_status()

        # Если что-то ушло в stderr (ошибки fsarchiver, приглашение sudo) — показываем.
        err = stderr.read().decode(errors="replace").strip()
        if err:
            print("\n[stderr]")
            print(err)

        # Итоговое сообщение по коду возврата.
        if exit_status == 0:
            print("\nГотово: системный бэкап создан.")
        else:
            print(f"\nБэкап завершился с ошибкой (код {exit_status}).")
        return exit_status
    finally:
        # Всегда закрываем соединение, даже при исключении.
        ssh.close()


if __name__ == "__main__":
    # Пробрасываем код возврата наружу — удобно для .bat и автоматизации.
    sys.exit(main())
