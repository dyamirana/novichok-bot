from types import SimpleNamespace
import sys
import asyncio
from unittest.mock import AsyncMock
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common


class DummyMessage:
    def __init__(self, text="", reply_to_message=None, thread_id=0):
        self.text = text
        self.reply_to_message = reply_to_message
        self.chat = SimpleNamespace(id=1, type="private")
        self.from_user = SimpleNamespace(id=123)
        self.replied = None
        self.message_thread_id = thread_id

    async def reply(self, text):
        self.replied = text


def test_taro_calls_respond(monkeypatch):
    original = DummyMessage(text="стоит ли продолжать?")
    msg = DummyMessage(text="/taro", reply_to_message=original)
    monkeypatch.setattr(common, "draw_cards", lambda n: ["Карта1", "Карта2", "Карта3"])
    mock = AsyncMock()
    monkeypatch.setattr(common, "respond_with_personality", mock)
    asyncio.run(common.cmd_taro(msg))
    assert original.replied == "Выпали карты: Карта1, Карта2, Карта3"
    mock.assert_awaited_once()
    args, kwargs = mock.call_args
    assert args[0] is msg
    assert args[1] == "Mrazota"
    assert args[2] == "стоит ли продолжать?"
    assert kwargs["reply_to"] is original
    assert "Карта1, Карта2, Карта3" in kwargs["additional_context"]
    assert "Сейчас ты гадаешь на таро" in kwargs["additional_context"]
    assert kwargs["model"] == "deepseek-reasoner"
