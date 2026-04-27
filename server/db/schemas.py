# datetime — тип для полей времени в Pydantic-схемах.
from datetime import datetime
# BaseModel — базовый класс Pydantic для валидации и сериализации данных.
from pydantic import BaseModel


class TagValueOut(BaseModel):
    """Схема ответа для одного тега — используется в GET /tags/latest.

    Pydantic автоматически сериализует ORM-объект TagValue в JSON.
    """
    # NodeId тега (например "ns=2;s=Application.Control.inProcess").
    tag_id: str
    # Человекочитаемое имя тега (например "inProcess").
    tag_name: str
    # Текущее значение тега в виде строки.
    value: str
    # Момент последнего обновления значения.
    updated_at: datetime

    # from_attributes=True — разрешает создавать схему из ORM-объекта (не только из dict).
    model_config = {"from_attributes": True}


class TagHistoryOut(BaseModel):
    """Схема ответа для одной записи истории — используется в GET /history/*.

    Поле tag_name добавляется через JOIN с таблицей tags в HistoryRepository.
    """
    # Первичный ключ записи в tag_history.
    id: int
    # ID тега из таблицы tags (может быть NULL для старых записей).
    tag_id: int | None = None
    # Имя тега — подставляется из Tag.name через JOIN, пустая строка если тег не найден.
    tag_name: str = ""
    # Значение тега в момент записи.
    value: str
    # Момент записи (UTC).
    recorded_at: datetime

    # from_attributes=True — для создания из ORM-объекта с динамическим атрибутом tag_name.
    model_config = {"from_attributes": True}


class CheckoutOut(BaseModel):
    """Схема ответа для одного испытания — используется в GET /checkouts.

    ended_at = None означает что испытание ещё активно.
    """
    # Первичный ключ испытания.
    id: int
    # Момент начала испытания (UTC).
    started_at: datetime
    # Момент конца испытания (UTC). None если испытание ещё идёт.
    ended_at: datetime | None = None

    # from_attributes=True — для создания из ORM-объекта Checkout.
    model_config = {"from_attributes": True}
