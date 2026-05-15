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
out.read()
print("Экспорты удалены.")

ssh.close()
print("\nГотово.")
