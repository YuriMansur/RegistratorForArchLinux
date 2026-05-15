"""
clear_db.py — полная очистка базы данных registrator.db.

Удаляет все данные из таблиц:
    tag_history  — история значений тегов
    checkouts    — испытания
    tag_values   — последние значения тегов
    tags         — справочник тегов

Структура таблиц сохраняется — только данные удаляются.
После очистки запускает VACUUM для уменьшения файла БД.
"""
# paramiko — SSH/SFTP подключение к серверу.
import paramiko
# os — для раскрытия пути к SSH-ключу.
import os

# ── Подключение к серверу ─────────────────────────────────────────────────────

# Загружаем SSH-ключ для подключения к серверу.
key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))

# Создаём SSH-клиент и подключаемся к серверу.
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.10.222", username="user", pkey=key)

print("Подключено к серверу 192.168.10.222")

# ── Предупреждение ────────────────────────────────────────────────────────────

print("\n⚠  ВНИМАНИЕ: все данные будут удалены безвозвратно!")
print("   Таблицы: tag_history, checkouts, tag_values, tags")
print("   Структура БД сохранится.\n")

# Запрашиваем подтверждение — случайный запуск не должен удалить данные.
answer = input("Введите YES для подтверждения: ").strip()
if answer != "YES":
    print("Отменено.")
    ssh.close()
    exit(0)

# ── Остановка сервиса ─────────────────────────────────────────────────────────

print("\nОстанавливаю registrator.service...")
# Останавливаем сервис чтобы не было активных соединений с БД во время очистки.
_, out, err = ssh.exec_command("echo 1111 | sudo -S systemctl stop registrator")
out.read()
err.read()
print("Сервис остановлен.")

# ── Очистка таблиц ────────────────────────────────────────────────────────────

# SQL-команды для очистки всех таблиц в правильном порядке (сначала зависимые).
sql = """
DELETE FROM tag_history;
DELETE FROM checkouts;
DELETE FROM tag_values;
DELETE FROM tags;
VACUUM;
"""

print("\nОчищаю базу данных...")
# Выполняем SQL через sqlite3 в командной строке на сервере.
_, out, err = ssh.exec_command(f'sqlite3 /home/user/registrator.db "{sql}"')
out_text = out.read().decode().strip()
err_text = err.read().decode().strip()

if err_text:
    print(f"Ошибка: {err_text}")
else:
    print("База данных очищена.")

# ── Проверка размера ──────────────────────────────────────────────────────────

_, out, _ = ssh.exec_command("du -sh /home/user/registrator.db")
size = out.read().decode().strip()
print(f"Размер БД после очистки: {size}")

# ── Запуск сервиса ────────────────────────────────────────────────────────────

print("\nЗапускаю registrator.service...")
_, out, err = ssh.exec_command("echo 1111 | sudo -S systemctl start registrator")
out.read()
err.read()

# Проверяем статус сервиса.
_, out, _ = ssh.exec_command("systemctl is-active registrator")
status = out.read().decode().strip()
print(f"Статус сервиса: {status}")

ssh.close()
print("\nГотово.")
