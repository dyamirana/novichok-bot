from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common

class DummyChat:
    def __init__(self, id=1):
        self.id = id

class DummyMessage:
    def __init__(self, text, reply_to_message=None, chat=None, message_id=1, from_user=None, bot=None):
        self.text = text
        self.reply_to_message = reply_to_message
        self.chat = chat or DummyChat()
        self.message_id = message_id
        self.from_user = from_user
        self.bot = bot

async def run_handle(message):
    await common.handle_message(message, "Mrazota")

def test_comment_triggers_mrazota(monkeypatch):
    post = SimpleNamespace(message_id=10, is_automatic_forward=True, sender_chat=SimpleNamespace(type="channel"))
    user = SimpleNamespace(is_bot=False, full_name="User")
    bot = SimpleNamespace(id=999)
    msg = DummyMessage("hi", reply_to_message=post, from_user=user, bot=bot, message_id=20)

    mock = AsyncMock()
    monkeypatch.setattr(common, "respond_with_personality", mock)
    monkeypatch.setattr(common, "is_group_allowed", lambda chat_id: True)
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common, "increment_count", AsyncMock(return_value=False))
    monkeypatch.setattr(common, "should_count_for_random", lambda m, p: False)

    asyncio.run(run_handle(msg))
    mock.assert_awaited_once()
    _, kwargs = mock.call_args
    assert kwargs["reply_to"] is post
    assert kwargs["reply_to_comment"] is msg
