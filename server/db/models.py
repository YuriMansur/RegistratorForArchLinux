# datetime — тип данных для полей времени в моделях.
# timezone — для создания timezone-aware datetime (UTC).
from datetime import datetime, timezone
# String, DateTime, Integer, ForeignKey — типы колонок SQLAlchemy.
from sqlalchemy import String, DateTime, Integer, ForeignKey
# Mapped, mapped_column — современный API SQLAlchemy 2.x для объявления колонок с типами.
from sqlalchemy.orm import Mapped, mapped_column
# Base — базовый класс всех ORM-моделей проекта.
from db.database import Base


class TagValue(Base):
    """Последнее известное значение OPC UA тега.

    Таблица хранит по одной строке на каждый тег — только актуальное значение.
    Обновляется при каждом получении данных от ПЛК.
    Используется эндпоинтом GET /tags/latest.
    """
    # Имя таблицы в SQLite.
    __tablename__ = "tag_values"

    # Первичный ключ — строковый NodeId тега (например "ns=2;s=Application.Control.inProcess").
    tag_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    # Человекочитаемое имя тега (например "inProcess").
    tag_name: Mapped[str] = mapped_column(String(255), default="")
    # Текущее значение тега, сериализованное в строку.
    value: Mapped[str] = mapped_column(String(1000), default="")
    # Момент последнего обновления — проставляется автоматически при INSERT и UPDATE.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Tag(Base):
    """Справочник тегов — метаданные: имя, единицы измерения, последнее значение.

    Создаётся автоматически при первом получении тега от ПЛК.
    Используется для связи TagHistory → Tag (JOIN по tag_id).
    """
    # Имя таблицы в SQLite.
    __tablename__ = "tags"

    # Автоинкрементный целочисленный идентификатор тега.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NodeId тега — уникален, используется как внешний ключ из TagHistory.
    node_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    # Короткое имя тега (например "values[0]").
    name: Mapped[str] = mapped_column(String(255))
    # Единицы измерения (например "МПа", "°C"). Пустая строка если не задано.
    units: Mapped[str] = mapped_column(String(50), default="")
    # Последнее значение тега — дублирует TagValue для удобства JOIN.
    value: Mapped[str] = mapped_column(String(1000), default="")
    # Время последнего обновления значения (UTC). NULL до первого получения данных.
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Checkout(Base):
    """Испытание — период записи данных от inProcess=True до End=True или inProcess=False.

    Каждое успешное испытание создаёт одну строку.
    Пустые испытания (0 строк в tag_history) удаляются автоматически в end_test().
    """
    # Имя таблицы в SQLite.
    __tablename__ = "checkouts"

    # Автоинкрементный идентификатор испытания.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Момент начала испытания (UTC) — проставляется в start_test().
    started_at: Mapped[datetime] = mapped_column(DateTime)
    # Момент конца испытания (UTC) — NULL пока испытание активно, проставляется в end_test().
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class TagHistory(Base):
    """История значений тегов, привязанная к испытанию.

    Одна строка = одно значение одного тега в один момент времени.
    Записывается в _on_poll_batch только когда _recording=True (идёт испытание).
    """
    # Имя таблицы в SQLite.
    __tablename__ = "tag_history"

    # Автоинкрементный идентификатор записи.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ID испытания из таблицы checkouts. Индексирован для быстрой выборки по испытанию.
    test_id: Mapped[int] = mapped_column(Integer, ForeignKey("checkouts.id"), nullable=True, index=True)
    # ID тега из таблицы tags. Индексирован для быстрой выборки по тегу.
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=True, index=True)
    # Значение тега в момент записи, сериализованное в строку.
    value: Mapped[str] = mapped_column(String(1000), default="")
    # Момент записи (UTC). Индексирован для быстрой выборки по диапазону дат.
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
