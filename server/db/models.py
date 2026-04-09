from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db.database import Base


class TagValue(Base):
    """Последнее известное значение OPC UA тега (не изменяется)."""
    __tablename__ = "tag_values"

    tag_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    tag_name: Mapped[str] = mapped_column(String(255), default="")
    value: Mapped[str] = mapped_column(String(1000), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Tag(Base):
    """Справочник тегов — заполняется вручную."""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    units: Mapped[str] = mapped_column(String(50), default="")
    value: Mapped[str] = mapped_column(String(1000), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Checkout(Base):
    """Испытание — период от inProcess=True до End=True."""
    __tablename__ = "checkouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class TagHistory(Base):
    """История значений тегов, привязанная к испытанию."""
    __tablename__ = "tag_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(Integer, ForeignKey("checkouts.id"), nullable=True, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=True, index=True)
    value: Mapped[str] = mapped_column(String(1000), default="")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
