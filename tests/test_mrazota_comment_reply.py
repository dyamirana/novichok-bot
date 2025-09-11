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
    user = SimpleNamespace(is_bot=False, full_name="User", id=1)
    bot = SimpleNamespace(id=999)
    msg = DummyMessage("hi", reply_to_message=post, from_user=user, bot=bot, message_id=20)

    mock = AsyncMock()
    monkeypatch.setattr(common, "respond_with_personality", mock)
    monkeypatch.setattr(common, "is_group_allowed", lambda chat_id: True)
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common, "increment_count", AsyncMock(return_value=False))
    monkeypatch.setattr(common, "should_count_for_random", lambda m, p: False)

    monkeypatch.setattr(common, "COMMENT_MERGE_WINDOW", 0.01)

    async def run():
        await common.handle_message(msg, "Mrazota")
        await asyncio.sleep(0.02)

    asyncio.run(run())
    mock.assert_awaited_once()
    args, kwargs = mock.call_args
    assert args[2] == msg.text
    assert kwargs["reply_to"] is msg
    assert kwargs["reply_to_comment"] is msg


def test_multiple_comments_combined(monkeypatch):
    post = SimpleNamespace(message_id=10, is_automatic_forward=True, sender_chat=SimpleNamespace(type="channel"))
    user = SimpleNamespace(is_bot=False, full_name="User", id=1)
    bot = SimpleNamespace(id=999)
    msg1 = DummyMessage("hi", reply_to_message=post, from_user=user, bot=bot, message_id=20)
    msg2 = DummyMessage("there", reply_to_message=post, from_user=user, bot=bot, message_id=21)

    mock = AsyncMock()
    monkeypatch.setattr(common, "respond_with_personality", mock)
    monkeypatch.setattr(common, "is_group_allowed", lambda chat_id: True)
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common, "increment_count", AsyncMock(return_value=False))
    monkeypatch.setattr(common, "should_count_for_random", lambda m, p: False)
    monkeypatch.setattr(common, "COMMENT_MERGE_WINDOW", 0.01)

    async def run():
        await common.handle_message(msg1, "Mrazota")
        await asyncio.sleep(0.005)
        await common.handle_message(msg2, "Mrazota")
        await asyncio.sleep(0.02)

    asyncio.run(run())
    mock.assert_awaited_once()
    args, kwargs = mock.call_args
    assert args[2] == f"{msg1.text} {msg2.text}"
    assert kwargs["reply_to"] is msg2
    assert kwargs["reply_to_comment"] is msg2
