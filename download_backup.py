import paramiko
import os
import sys
from pathlib import Path

key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.10.222", username="user", pkey=key)
sftp = ssh.open_sftp()

# Получить список системных бэкапов
_, out, _ = ssh.exec_command("ls -t /home/user/system_backups/*.fsa 2>/dev/null")
backups = [line.strip() for line in out.read().decode().splitlines() if line.strip()]

if not backups:
    print("Нет системных бэкапов на сервере.")
    sftp.close()
    ssh.close()
    sys.exit(1)

print("Доступные бэкапы:")
for i, b in enumerate(backups):
    print(f"  [{i}] {b}")

idx = input(f"\nВыберите номер [0 = последний]: ").strip()
idx = int(idx) if idx else 0
remote_path = backups[idx]
filename = remote_path.split("/")[-1]

save_dir = Path.home() / "Downloads"
save_dir.mkdir(exist_ok=True)
local_path = save_dir / filename

print(f"\nСкачиваю {filename} → {local_path} ...")

def progress(transferred, total):
    pct = transferred / total * 100
    print(f"\r  {pct:.1f}%  ({transferred // 1024 // 1024} MB / {total // 1024 // 1024} MB)", end="", flush=True)

sftp.get(remote_path, str(local_path), callback=progress)
print(f"\nГотово: {local_path}")

sftp.close()
ssh.close()

