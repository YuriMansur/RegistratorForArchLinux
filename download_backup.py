# SSH/SFTP клиент
import paramiko      
# Для раскрытия пути ~/.ssh/...
import os       
# Для sys.exit при ошибке        
import sys  
# Работа с путями файловой системы             
from pathlib import Path

# SSH-подключение

# Загрузка Ed25519 приватный ключ
key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key")) 
# Создие SSH-клиента
ssh = paramiko.SSHClient()           
# Автоматически принимает ключ хоста (без ручного подтверждения)
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  
# Подключается к серверу по IP с ключом
ssh.connect("192.168.10.222", username="user", pkey=key)   
# Открывает SFTP-сессию поверх SSH для передачи файлов
sftp = ssh.open_sftp()  # 

# Получение списка бэкапов
# Запускает ls на сервере, сортирует по дате (новые первыми)
_, out, _ = ssh.exec_command("ls -t /home/user/system_backups/*.fsa 2>/dev/null") 
# Читает вывод, разбивает по строкам, убирает пустые
backups = [line.strip() for line in out.read().decode().splitlines() if line.strip()]

# Если бэкапов нет
if not backups:                  
    # Сообщениев консоль
    print("Нет системных бэкапов на сервере.")
    # закрываем SFTP перед выходом
    sftp.close()                  
    # закрываем SSH перед выходом
    ssh.close()     
    # завершаем с кодом ошибки 1              
    sys.exit(1)                  

# Выбор бэкапа
# Вывод заголовка списка в консоль
print("Доступные бэкапы:")           
# Перебирает все найденные бэкапы             
for i, b in enumerate(backups):    
# выводиТ индекс и полный путь к файлу             
    print(f"  [{i}] {b}")                  

idx = input(f"\nВыберите номер [0 = последний]: ").strip()  # спрашиваем номер у пользователя
idx = int(idx) if idx else 0                      # если ввод пустой — берём 0 (самый свежий)

remote_path = backups[idx]                        # полный путь к выбранному файлу на сервере
filename = remote_path.split("/")[-1]             # извлекаем только имя файла из пути

save_dir = Path.home() / "Downloads"              # папка назначения: ~/Downloads/
save_dir.mkdir(exist_ok=True)                     # создаём папку если её нет
local_path = save_dir / filename                  # полный локальный путь для сохранения

print(f"\nСкачиваю {filename} → {local_path} ...")  # информируем пользователя о начале скачивания

# ── Скачивание с прогресс-баром ────────────────────────────────────────────────

def progress(transferred: int, total: int) -> None:
    """Callback для sftp.get() — вызывается при каждом полученном блоке данных."""
    pct = transferred / total * 100                                      # вычисляем процент выполнения
    print(f"\r  {pct:.1f}%  ({transferred // 1024 // 1024} MB / {total // 1024 // 1024} MB)",  # выводим прогресс в одну строку
          end="", flush=True)                                            # \r перезаписывает строку, flush — сразу в терминал

sftp.get(remote_path, str(local_path), callback=progress)  # скачиваем файл с сервера, передаём callback для прогресса
print(f"\nГотово: {local_path}")                           # сообщаем об успешном завершении

# ── Закрытие соединения ────────────────────────────────────────────────────────

sftp.close()  # закрываем SFTP-сессию
ssh.close()   # закрываем SSH-соединение
