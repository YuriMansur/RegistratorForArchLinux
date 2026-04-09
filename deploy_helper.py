# 
import paramiko
# 
import os

from pathlib import Path

#Ключ по-умолчанию для подключения к серверу (можно заменить на другой, если нужно)
key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))
# Установка SSH-соединения с сервером 
ssh = paramiko.SSHClient()
# Разрешить добавление нового хоста в known_hosts
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# Подключение к удаленному серверу с указание пользователя и  ключа
ssh.connect("192.168.10.222", username = "user", pkey = key)
# Открытие SFTP-сессии для передачи файлов
sftp = ssh.open_sftp()

# Путь к локальной папке с файлами сервера
server_dir = Path("server")

# Проходим по всем файлам в папке сервера и загружаем их на удаленный сервер, сохраняя структуру папок
for f in server_dir.rglob("*"):
    # Если это папка, то пропускаем (она будет создана на сервере при загрузке файлов)
    if f.is_dir():
        continue
    # Пропускаем файлы и папки, которые не нужны на сервере
    rel = f.as_posix()
    # Игнорируем папки __pycache__, .venv и файлы с расширением .db
    if "__pycache__" in rel or ".venv" in rel or rel.endswith(".db"):
        continue
    # Формируем удаленный путь, сохраняя структуру папок
    remote = "/home/user/registrator/" + rel
    # Создаем удаленную папку, если ее нет, и загружаем файл
    remote_dir = remote.rsplit("/", 1)[0]
    # Создаём папку на сервере (mkdir -p), чтобы гарантировать её существование перед загрузкой файла
    ssh.exec_command("mkdir -p " + remote_dir)[1].read()
    # Загружаем файл на сервер
    sftp.put(str(f), remote)
    # Выводим в консоль имя загруженного файла для отслеживания прогресса
    print("ok", rel)

# Закрытие SFTP-сессии
sftp.close()
# Закрытие SSH-соединения
ssh.close()
# вывод в консоль об успехе завершения процесса
print("all done")
