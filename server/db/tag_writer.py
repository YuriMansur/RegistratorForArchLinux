"""
tag_writer — потокобезопасная запись значений OPC UA тегов в SQLite.

Вызывается из client_manager._on_poll_batch() и _on_data_received().
Работает в потоке OPC UA worker'а, поэтому использует синхронный SessionLocal.

Таблицы которые обновляются:
    TagValue   — последнее значение каждого тега (upsert по tag_id)
    Tag        — справочник тегов (upsert по node_id)
    TagHistory — история значений во время испытания (только если record_history=True)
"""
# datetime — для явного проставления времени записи.
# timezone — для создания UTC-aware datetime.
from datetime import datetime, timezone
# SessionLocal — синхронная сессия SQLite для фоновых потоков.
from db.database import SessionLocal
# ORM-модели таблиц которые обновляет этот модуль.
from db.models import TagValue, Tag, TagHistory


def write_tag(
    tag_id: str,           # NodeId тега, например "ns=2;s=Application.Control.inProcess"
    value,                 # значение тега: bool, float, int, str, list или tuple
    tag_name: str = "",    # человекочитаемое имя тега для отображения в таблице
    record_history: bool = True,       # True — писать строку в TagHistory
    test_id: int | None = None,        # ID испытания для TagHistory.test_id
    recorded_at: datetime | None = None,  # явный timestamp; None = datetime.now(UTC)
) -> None:
    """Записать значение тега в БД.

    Если value — список/кортеж (массивный тег), каждый элемент пишется отдельно
    как tag_id[i]. Это позволяет хранить и отображать каждый элемент массива независимо.

    Всегда обновляет TagValue (последнее значение) и Tag (справочник).
    Пишет в TagHistory только если record_history=True И идёт испытание.
    """
    # Массивный тег — разворачиваем каждый элемент в отдельный вызов write_tag.
    if isinstance(value, (list, tuple)):
        # Фиксируем общий timestamp для всех элементов массива (единый момент опроса).
        now = recorded_at if recorded_at is not None else datetime.now(timezone.utc)
        for i, item in enumerate(value):
            # Рекурсивный вызов для каждого элемента с индексом в имени.
            write_tag(
                tag_id=f"{tag_id}[{i}]",
                value=item,
                tag_name=f"{tag_name}[{i}]" if tag_name else f"{tag_id}[{i}]",
                record_history=record_history,
                test_id=test_id,
                recorded_at=now,
            )
        # После обработки всех элементов — выходим, скалярная логика ниже не нужна.
        return

    # Приводим значение к строке для хранения в VARCHAR-колонках.
    serialized = _serialize(value)
    # Используем переданный timestamp или текущее время UTC.
    now = recorded_at if recorded_at is not None else datetime.now(timezone.utc)

    # Открываем синхронную сессию — она существует только на время этого вызова.
    db = SessionLocal()
    try:
        # ── TagValue: хранит последнее значение каждого тега ─────────────────────
        # Ищем существующую запись по первичному ключу (tag_id).
        row = db.get(TagValue, tag_id)
        if row is None:
            # Первое появление тега — создаём новую запись.
            row = TagValue(tag_id=tag_id, tag_name=tag_name or tag_id)
            db.add(row)
        # Обновляем значение и время — INSERT или UPDATE в одном месте.
        row.value = serialized
        row.updated_at = now
        # Обновляем имя тега если оно пришло (при первом создании имя могло быть пустым).
        if tag_name:
            row.tag_name = tag_name

        # ── Tag: справочник тегов для JOIN с TagHistory ───────────────────────────
        # Ищем тег по NodeId — unique index обеспечивает быстрый поиск.
        tag_row = db.query(Tag).filter(Tag.node_id == tag_id).first()
        if tag_row is None:
            # Тег встречается первый раз — создаём запись в справочнике.
            tag_row = Tag(node_id=tag_id, name=tag_name or tag_id, units="")
            db.add(tag_row)
            # flush() выполняет INSERT без commit — нам нужен tag_row.id для TagHistory.
            db.flush()
        # Обновляем текущее значение и время в справочнике.
        tag_row.value = serialized
        tag_row.updated_at = now
        # Если имя тега было задано как node_id (первое создание без имени) — уточняем.
        if tag_name and tag_row.name == tag_id:
            tag_row.name = tag_name
        # Сохраняем id тега для внешнего ключа в TagHistory.
        tag_fk: int = tag_row.id

        # ── TagHistory: история значений во время испытания ───────────────────────
        if record_history:
            # Пишем строку истории — одна строка на каждый тег на каждый момент опроса.
            db.add(TagHistory(
                test_id=test_id,      # привязка к текущему испытанию
                tag_id=tag_fk,        # внешний ключ на справочник тегов
                value=serialized,     # значение тега в этот момент
                recorded_at=now,      # единый timestamp для всей группы опроса
            ))

        # Фиксируем все изменения в одной транзакции.
        db.commit()
    finally:
        # Всегда закрываем сессию — даже если выбросило исключение.
        db.close()


def _serialize(value) -> str:
    """Привести значение тега к строке для хранения в VARCHAR-колонках SQLite.

    Список/кортеж → строка с округлёнными до 4 знаков числами.
    float → строка с 6 знаками после запятой (избегаем 0.30000000000000004).
    Всё остальное → str().
    """
    if isinstance(value, (list, tuple)):
        # Округляем float-элементы до 4 знаков — компромисс точность/размер.
        return str([round(float(v), 4) if isinstance(v, float) else v for v in value])
    if isinstance(value, float):
        # 6 знаков — достаточно для инженерных измерений, меньше шума.
        return str(round(value, 6))
    # bool, int, str — просто преобразуем в строку.
    return str(value)
