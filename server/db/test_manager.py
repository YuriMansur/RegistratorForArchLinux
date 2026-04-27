"""
test_manager — управление записями об испытаниях в таблице checkouts.

Испытание (checkout) — это период между inProcess=True и End=True на ПЛК.
Каждое испытание хранится как строка в таблице checkouts с полями:
    id         — уникальный номер испытания
    started_at — момент начала (UTC)
    ended_at   — момент конца (UTC), NULL пока идёт запись

Модуль предоставляет два метода:
    start_test() — вызывается когда ПЛК выставил inProcess=True
    end_test()   — вызывается когда ПЛК выставил End=True или inProcess=False
"""

# datetime — для получения текущего времени в UTC при создании/закрытии записи.
from datetime import datetime, timezone
# SessionLocal — фабрика синхронных сессий SQLite (используется в фоновых потоках).
from db.database import SessionLocal
# Checkout — ORM-модель таблицы checkouts.
from db.models import Checkout


def start_test() -> int:
    """
    Создать новую запись об испытании в таблице checkouts.

    Вызывается из client_manager когда ПЛК выставил inProcess=True.
    Фиксирует момент начала испытания в UTC.

    Returns:
        int: id созданной записи — используется при записи tag_history
             и при закрытии испытания через end_test().
    """
    # Открываем синхронную сессию БД — используем sync engine так как
    # client_manager работает в отдельном потоке вне asyncio event loop.
    db = SessionLocal()
    try:
        # Создаём новую запись: started_at = сейчас (UTC), ended_at = NULL.
        checkout = Checkout(started_at=datetime.now(timezone.utc))
        # Регистрируем объект в сессии для последующего INSERT.
        db.add(checkout)
        # Фиксируем транзакцию — запись появляется в БД.
        db.commit()
        # Обновляем объект из БД чтобы получить сгенерированный id.
        db.refresh(checkout)
        # Возвращаем id — он будет передан в tag_history.test_id для связи.
        return checkout.id
    finally:
        # Всегда закрываем сессию, даже если выбросило исключение.
        db.close()


def end_test(test_id: int) -> None:
    """
    Завершить испытание: записать ended_at или удалить если данных нет.

    Вызывается из client_manager когда ПЛК выставил End=True или inProcess=False.

    Логика:
        - Если в tag_history есть хотя бы одна строка для этого испытания →
          записываем ended_at = сейчас (UTC). Испытание сохраняется в истории.
        - Если данных нет (испытание длилось слишком мало) →
          удаляем запись полностью. Пустые испытания не засоряют историю.

    Args:
        test_id: id испытания, полученный из start_test().
    """
    # Импортируем TagHistory здесь чтобы избежать циклического импорта
    # (test_manager импортируется из models через database).
    from db.models import TagHistory

    db = SessionLocal()
    try:
        # Ищем запись испытания по id.
        checkout = db.get(Checkout, test_id)

        # Если запись уже удалена (например, при параллельном вызове) — выходим.
        if not checkout:
            return

        # Проверяем есть ли хоть одна строка данных для этого испытания.
        # Используем .first() а не .count() — он останавливается на первой записи,
        # не сканирует всю таблицу. Для проверки существования это быстрее.
        has_data = db.query(TagHistory).filter(TagHistory.test_id == test_id).first() is not None

        if has_data:
            # Есть данные — закрываем испытание нормально.
            checkout.ended_at = datetime.now(timezone.utc)
            db.commit()
        else:
            # Данных нет — испытание пустое (слишком короткое или сбой записи).
            # Удаляем запись чтобы она не появлялась в списке испытаний у клиента.
            db.delete(checkout)
            db.commit()
    finally:
        # Всегда закрываем сессию, даже если выбросило исключение.
        db.close()
