import random
from dataclasses import dataclass
from typing import ClassVar, Dict, Optional

from .config import PROMPTS_DIR


MAIN_PROMPT = (
    "Ты отвечаешь в чате, принимая различные роли. "
    "Следуй выбранной личности и соблюдай общий стиль общения. Соблюдай четко указания, это важно чтобы ответы выглядели естественно. "
)

# Заполняемый словарь сленга: {"сленг": "значение"}
SLANG_DICT: Dict[str, str] = {
    "теневой": "парень стримерши, которая говорит что у нее нет парня. Разводят симпов на донаты",
    "мразИИна": "ии версия стримерши марамойки Мразота",
    "марамойка": "стримерша, которая разводит симпов на донаты, часто использует сексуальный контент",
    "бусти": "платформа для монетизации контента, где стримеры выкладывают эксклюзивные материалы, а девушки выкладывают свои фото и видео. Как онлифанс",
    "8333": "локальный мем означающий сколько часов нужно смотреть стрим, чтобы трахнуть мразоту. Недостижимая цель",
    "новичок": "залетный участник чата, который только недавно зашел в чат, но возможно давно уже смотрим стримершу, не выкупает постиронию и шутки",
    "готика": "игра, которую обещает поиграть Мэддисон, но не играет.",
    "куплинов": "персонаж, который часто используется в шутках, как пример того, что он бы уже прошел игру или сделал что-то лучше",
    "ключ": "локальный мем когда в чат залетела какая-то бабка Наталья и требовала его отдать",
}


def get_prompt(name: str) -> str:
    """Load personality prompt from file if exists."""
    file = PROMPTS_DIR / f"{name}.txt"
    try:
        return file.read_text(encoding="utf-8")
    except Exception:
        return ""


MOOD_PROMPTS: Dict[str, str] = {
    "игривое": "Ты в игривом настроении, подшучивай и дразни собеседника.",
    "веселое": "Ты в веселом настроении, излучай позитив и шуми.",
    "нейтральное": "У тебя нейтральное настроение, отвечай спокойно и ровно.",
    "злое": "Ты в злом настроении, можно огрызаться и саркастично подколоть.",
    "агрессивное": "Ты в агрессивном настроении, можешь резко и грубо отвечать.",
}


@dataclass
class Personality:
    name: ClassVar[str]
    mood_weights: ClassVar[Dict[str, int]] = {}

    def get_mood_prompt(self) -> str:
        if not self.mood_weights:
            return ""
        moods = list(MOOD_PROMPTS.keys())
        probs = [self.mood_weights.get(mood, 1) for mood in moods]
        mood = random.choices(moods, weights=probs, k=1)[0]
        text = MOOD_PROMPTS[mood]
        return f"Сейчас у тебя {mood} настроение. {text}"


class JoePeach(Personality):
    name = "JoePeach"
    mood_weights = {
        "игривое": 3,
        "веселое": 3,
        "нейтральное": 2,
        "злое": 1,
        "агрессивное": 1,
    }


class Mrazota(Personality):
    name = "Mrazota"
    mood_weights = {
        "игривое": 1,
        "веселое": 1,
        "нейтральное": 2,
        "злое": 3,
        "агрессивное": 3,
    }


class Kuplinov(Personality):
    name = "Kuplinov"


PERSONALITIES: Dict[str, Personality] = {
    cls.name: cls() for cls in (JoePeach, Mrazota, Kuplinov)
}


def get_personality(name: str) -> Optional[Personality]:
    return PERSONALITIES.get(name)


def get_mood_prompt(personality: str) -> str:
    """Return random mood prompt for selected personalities."""
    pers = get_personality(personality)
    if not pers:
        return ""
    return pers.get_mood_prompt()
