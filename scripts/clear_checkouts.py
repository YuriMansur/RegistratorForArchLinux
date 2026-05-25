import paramiko
import os

key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.10.222", username="user", pkey=key)

print("Подключено к серверу 192.168.10.222")
print("\n⚠  ВНИМАНИЕ: все папки экспортов будут удалены!")
print("   Файлы:   ~/registrator/exports/checkout_*\n")

answer = input("Введите YES для подтверждения: ").strip()
if answer != "YES":
    print("Отменено.")
    ssh.close()
    exit(0)

print("Удаляю папки экспортов...")
_, out, err = ssh.exec_command("rm -rf /home/user/registrator/exports/checkout_*")
# Всегда дренируем оба пайпа — иначе paramiko может зависнуть, если в stderr что-то осталось.
out.read()
err_text = err.read().decode().strip()
# exit_status — реальный код возврата команды на сервере (0 = успех).
exit_code = out.channel.recv_exit_status()

if exit_code != 0 or err_text:
    # Реальная ошибка — не врём пользователю что всё удалилось.
    print(f"Ошибка (exit={exit_code}): {err_text or '(нет stderr)'}")
    ssh.close()
    exit(1)

print("Экспорты удалены.")

ssh.close()
print("\nГотово.")
