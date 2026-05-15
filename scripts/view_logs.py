"""
view_logs.py — утилита для просмотра логов сервера через SSH.

Подключается по SSH (Ed25519-ключ) и читает логи systemd-сервиса registrator
через journalctl. Можно смотреть последние N строк или следить в реальном времени.

Использование:
    python view_logs.py
"""

import paramiko          # SSH-клиент
import os                # для раскрытия пути ~/.ssh/...
import sys               # для sys.exit при ошибке

# ── SSH-подключение ────────────────────────────────────────────────────────────

key = paramiko.Ed25519Key.from_private_key_file(os.path.expanduser("~/.ssh/registrator_key"))  # загружаем Ed25519 приватный ключ
ssh = paramiko.SSHClient()                                                                       # создаём SSH-клиент
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())                                        # автоматически принимаем ключ хоста
ssh.connect("192.168.10.222", username="user", pkey=key)                                         # подключаемся к серверу

# ── Команда: последние 50 строк + следим в реальном времени ──────────────────

cmd = "journalctl -u registrator -n 50 -f --no-pager"  # -n 50 показывает хвост, -f следит за новыми строками

# ── Выполняем команду и выводим результат ─────────────────────────────────────

print(f"\n{'─' * 60}")  # разделитель для читаемости

_, out, _ = ssh.exec_command(cmd, get_pty=True)  # выполняем команду, get_pty нужен для live-режима

try:
    for line in iter(out.readline, ""):  # читаем построчно пока есть данные
        print(line, end="")              # выводим строку в консоль (end="" — нет двойных переносов)
        sys.stdout.flush()               # сразу выводим в терминал без буферизации
except KeyboardInterrupt:
    print("\n\nОстановлено.")            # Ctrl+C — выходим из live-режима корректно

# ── Закрытие соединения ────────────────────────────────────────────────────────

ssh.close()  # закрываем SSH-соединение
