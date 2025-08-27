import random

MAJOR_ARCANA = [
    "Шут",
    "Маг",
    "Верховная Жрица",
    "Императрица",
    "Император",
    "Иерофант",
    "Влюбленные",
    "Колесница",
    "Сила",
    "Отшельник",
    "Колесо Фортуны",
    "Справедливость",
    "Повешенный",
    "Смерть",
    "Умеренность",
    "Дьявол",
    "Башня",
    "Звезда",
    "Луна",
    "Солнце",
    "Страшный Суд",
    "Мир",
]


def draw_cards(count: int = 3) -> list[str]:
    """Return ``count`` unique tarot card names."""
    count = max(1, min(count, len(MAJOR_ARCANA)))
    return random.sample(MAJOR_ARCANA, count)
