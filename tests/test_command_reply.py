from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common


class DummyUser:
    def __init__(self, id=1):
        self.id = id


class DummyMessage:
    def __init__(self, reply_to_message=None, from_user=None):
        self.reply_to_message = reply_to_message
        self.from_user = from_user or DummyUser()

    async def delete(self):
        pass

def test_command_replies_to_original(monkeypatch):
    original = SimpleNamespace(text="hi", message_id=123)
    msg = DummyMessage(reply_to_message=original)
    mock = AsyncMock()
    monkeypatch.setattr(common, "respond_with_personality", mock)
    asyncio.run(common.cmd_kuplinov(msg))
    mock.assert_awaited_once()
    assert mock.call_args.kwargs.get("reply_to") is original
