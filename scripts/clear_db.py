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

# DELETE'ы выполняем одним вызовом — каждый statement в sqlite3 CLI автокоммитится сам.
# Порядок: tag_history → checkouts → tag_values → tags (сначала зависимые от ключей).
delete_sql = (
    "DELETE FROM tag_history; "
    "DELETE FROM checkouts; "
    "DELETE FROM tag_values; "
    "DELETE FROM tags;"
)


def _run_remote(cmd: str) -> tuple[int, str, str]:
    """Выполнить команду на сервере, вернуть (exit_code, stdout, stderr).
    Всегда дренирует оба пайпа — иначе paramiko может зависнуть."""
    _, out, err = ssh.exec_command(cmd)
    out_text = out.read().decode().strip()
    err_text = err.read().decode().strip()
    # recv_exit_status возвращает реальный код возврата команды на сервере.
    code = out.channel.recv_exit_status()
    return code, out_text, err_text


print("\nОчищаю базу данных (DELETE)...")
# -bail заставляет sqlite3 остановиться при первой ошибке вместо тихого продолжения.
code, _, err_text = _run_remote(f'sqlite3 -bail /home/user/registrator.db "{delete_sql}"')
if code != 0 or err_text:
    print(f"Ошибка DELETE (exit={code}): {err_text or '(нет stderr)'}")
else:
    print("Таблицы очищены.")

# VACUUM — отдельным вызовом. Внутри транзакции его выполнять нельзя, поэтому даём ему свой CLI-запуск.
print("Сжимаю файл БД (VACUUM)...")
code, _, err_text = _run_remote('sqlite3 -bail /home/user/registrator.db "VACUUM;"')
if code != 0 or err_text:
    print(f"Ошибка VACUUM (exit={code}): {err_text or '(нет stderr)'}")
else:
    print("База данных сжата.")

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
