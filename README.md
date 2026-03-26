# Registrator

Клиент-серверное приложение:
- **Сервер** — Python + FastAPI, запускается на Arch Linux
- **Клиент** — Python + PyQt6, запускается на Windows

---

## Запуск сервера (на Linux)

```bash
cd server
pip install -r requirements.txt
python main.py
# или: uvicorn main:app --host 0.0.0.0 --port 8000
```

Swagger-документация: `http://localhost:8000/docs`

> Убедись что порт 8000 открыт в firewall:
> `sudo ufw allow 8000`

---

## Запуск клиента (на Windows)

```bat
cd client
pip install -r requirements.txt
python main.py
```

При первом запуске откроется предупреждение — нажми **Настройки**,
введи IP-адрес Linux-машины (например `192.168.1.50`) и порт `8000`.

---

## Структура

```
server/
  main.py          — FastAPI приложение
  database.py      — SQLAlchemy + SQLite
  models.py        — ORM-модели
  schemas.py       — Pydantic-схемы
  routers/
    records.py     — CRUD /records

client/
  main.py          — точка входа Qt
  config.py        — загрузка/сохранение IP сервера
  api_client.py    — HTTP-запросы к серверу
  ui/
    main_window.py     — главное окно + таблица
    record_form.py     — форма добавления/редактирования
    settings_dialog.py — настройки подключения
```
