import struct
from typing import List, Union

class ConvertProtocolData:

# Словари
    # C вложенным кортежем порядка байт в зависимости от нотации
    BYTE_ORDER = {
        "ABCD": (0, 1, 2, 3),
        "BADC": (1, 0, 3, 2),
        "CDAB": (2, 3, 0, 1),
        "DCBA": (3, 2, 1, 0),
    }
    
    # Соттвтетствия типу данных для модуля struct
    TYPE_FORMAT = {
        "float32": "f",
        "int32": "i",
        "uint32": "I",
    }

# Классовый метод преобразования 4 байтых переменных
    @classmethod
    def convert_4bytes(
        cls,
        data: Union[int, float, List[int]],
        dtype: str,
        endianess: str
    ) -> Union[float, int, List[int]]:
        """
        Преобразует 32 бита данных между значением и двумя 16-битными словами.
        Работает в двух направлениях:
        - VALUE → WORDS: Преобразует int32/float32 в список из двух 16-битных слов.
        - WORDS → VALUE: Преобразует список из двух 16-битных слов обратно в int32/float32

        P. S. Может так же преобюразовыывать и uint32

        :param cls: автоматическая ссылка для использования словарей класса
        :param data: значение для преобразования (int, float или список из двух слов).
        :param dtype: тип данных: "float32", "int32", "uint32
        :param endianess: порядок байт: "ABCD", "BADC", "CDAB", "DCBA"
        :param return: преобразованное значение (список из двух слов или int/float
        """

    # Приведение к стандартному виду
        # Для типов данных
        dtype = dtype.lower()
        # Для нотации
        endianess = endianess.upper()

    # Валидация
        if dtype not in cls.TYPE_FORMAT:
            raise ValueError(f"Unsupported type: {dtype}")
        
    # Получение порядка байт и формат типа
        # Для типов данных
        fmt = cls.TYPE_FORMAT[dtype]
        # Для нотации
        order = cls.BYTE_ORDER[endianess]
        
    # VALUE → WORDS
        #Если входное значение — число (int или float), упаковываем в 4 байта.
        if isinstance(data, (int, float)):
            raw = struct.pack(">"+fmt, data)
            reordered = bytes(raw[i] for i in order)

            return [
                int.from_bytes(reordered[0:2], "big"),
                int.from_bytes(reordered[2:4], "big"),]

    # WORDS → VALUE
        # Если входные данные — список из двух слов:
            
            # Применяем обратную перестановку для восстановления исходного порядка.
            
        if isinstance(data, list) and len(data) == 2:
            # Разбираем слова на 4 байта.
            raw = (
                data[0].to_bytes(2, "big") +
                data[1].to_bytes(2, "big"))
            # Конфигурирует порядок
            inv = [order.index(i) for i in range(4)]
            # Собирает в нужном порядке
            restored = bytes(raw[i] for i in inv)

            # Распаковывает в число (int или float).
            return struct.unpack(">"+fmt, restored)[0]

        raise ValueError("Invalid input data")
    
# Статический метод для битового перобразования переменных
    @staticmethod
    def register_bits(
        reg_or_bits: Union[int, List[int]],
        bit: Union[int, None] = None,
        byte_order: List[int] = [0, 1],              # порядок байт
        high_byte_bit_order: List[int] = [0,1,2,3,4,5,6,7],  # порядок бит в старшем байте
        low_byte_bit_order: List[int] = [0,1,2,3,4,5,6,7]    # порядок бит в младшем байте
    ) -> Union[int, List[int]]:
        """
        Преобразовывает регистры и биты.
        Работает в двух направлениях.
        
        :param regs_or_bits: Регистр или группа битов
        :param bit: Номер извлекаемого бита
        :param byte_order: Порядок байт
        :param high_byte_bit_order: Порядок бит в старшем байте
        :param low_byte_bit_order: Порядок бит в младшем байте
        """    
    # Валидация
        # Проверка чтобы были указаны оба индекса порядка байт
        if len(byte_order) != 2 or set(byte_order) != {0,1}:
            raise ValueError("byte_order должен содержать два индекса 0 и 1")
        # Проверка чтобы были указаны все индексы порядка бит ПЕРВОГО байта
        if len(high_byte_bit_order) != 8 or set(high_byte_bit_order) != set(range(8)):
            raise ValueError("high_byte_bit_order должен содержать все числа 0..7")
        # Проверка чтобы были указаны все индексы порядка бит ВТОРОГО байта
        if len(low_byte_bit_order) != 8 or set(low_byte_bit_order) != set(range(8)):
            raise ValueError("low_byte_bit_order должен содержать все числа 0..7")
        
    # Замена порядка бит в байтах
        def reorder_byte(byte: int, order: List[int]) -> int:
            return sum(((byte >> i) & 1) << order.index(i) for i in range(8))

    # Преобразование WORD → BITS
        if isinstance(reg_or_bits, int):
            # Считывание значение значения аргумента
            reg = reg_or_bits

            # Проверка значения на превышение размера 16 бит
            if not (0 <= reg <= 0xFFFF):
                raise ValueError("Регистровое значение должно быть 0..65535")

            # Разделение на байты [high, low]
            bytes_ = [(reg >> 8) & 0xFF, reg & 0xFF]
            # Перестановка бит в каждом байте
            bytes_ = [
                reorder_byte(bytes_[0], high_byte_bit_order),
                reorder_byte(bytes_[1], low_byte_bit_order)]
            # Перестановка байт в заданном порядке
            bytes_ = [bytes_[i] for i in byte_order]

            # Формирование 16 битной переменной
            reg = (bytes_[0] << 8) | bytes_[1]
            # Побитовая раскладка из 16 битной переменной
            bits = [(reg >> i) & 1 for i in range(16)]
            # Проверка номера извлекаемого бита
            if bit is not None:
                if not (0 <= bit <= 15):
                    raise ValueError("Номер бита должен быть 0..15")
                return bits[bit]
            return bits

    # Преобразование BITS → WORD
        elif isinstance(reg_or_bits, list):
            bits = reg_or_bits
            # Проверка на содеражание 16 бит 
            if len(bits) != 16 or any(b not in (0,1) for b in bits):
                raise ValueError("Список должен содержать ровно 16 бит (0 или 1)")

            # Сбор байтов из битов
            bytes_ = [sum(bits[i + j] << j for j in range(8)) for i in (0,8)]
            # Перестановка бит в каждом байте
            bytes_ = [
                reorder_byte(bytes_[0], high_byte_bit_order),
                reorder_byte(bytes_[1], low_byte_bit_order)
            ]
            # Перестановка байт
            bytes_ = [bytes_[i] for i in byte_order]

            return (bytes_[0] << 8) | bytes_[1]

        else:
            raise ValueError("reg_or_bits должен быть int или list из 16 бит")

    @staticmethod
    def to_signed_16(value: int) -> int:
        """
        Преобразует беззнаковое 16-битное значение в знаковое.

        :param value: беззнаковое 16-битное значение (0..65535)
        :return: знаковое значение (-32768..32767)
        """
        if value >= 0x8000:
            return value - 0x10000
        return value


