from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# ССылка на SQLite файл БД. В нашем случае — в той же папке, что и сервер.
DATABASE_URL = "sqlite:///./registrator.db"
# SQLAlchemy Engine — управляет соединениями с БД, создаёт их по мере необходимости.
engine = create_engine( DATABASE_URL, connect_args={"check_same_thread": False})
# Сессия для работы с БД: создаётся при входе в эндпоинт и закрывается при выходе (даже при ошибке).
SessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)


# Базовый класс для моделей SQLAlchemy
class Base(DeclarativeBase):
    pass


# Dependency для получения сессии БД в эндпоинтах FastAPI
def get_db():
    """Создаёт новую сессию БД для каждого запроса и гарантирует её закрытие после обработки."""
    # Сессия создаётся при входе в эндпоинт и закрывается при выходе (даже при ошибке).
    db = SessionLocal()
    try:
        # yield позволяет использовать эту функцию как контекстный менеджер в Depends(get_db).
        yield db
    finally:
        # Закрываем сессию после обработки запроса, освобождая ресурсы.
        db.close()
