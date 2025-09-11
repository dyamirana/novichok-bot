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
    def __init__(
        self,
        text,
        reply_to_message=None,
        chat=None,
        message_id=1,
        from_user=None,
        bot=None,
        thread_id=0,
    ):
        self.text = text
        self.reply_to_message = reply_to_message
        self.chat = chat or DummyChat()
        self.message_id = message_id
        self.from_user = from_user
        self.bot = bot
        self.message_thread_id = thread_id

    async def reply(self, text):
        return SimpleNamespace(message_id=42)

    async def answer(self, text):
        return SimpleNamespace(message_id=43)

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


class DummyBot:
    async def send_chat_action(self, chat_id, action):
        pass


def test_comment_history_used(monkeypatch):
    user = SimpleNamespace(is_bot=False, full_name="User", id=1)
    bot = DummyBot()
    msg = DummyMessage("hello", from_user=user, bot=bot, thread_id=5)

    monkeypatch.setattr(common, "is_group_allowed", lambda chat_id: True)
    get_thread = AsyncMock(return_value=[])
    get_history = AsyncMock(return_value=[])
    monkeypatch.setattr(common, "get_thread", get_thread)
    monkeypatch.setattr(common, "get_history", get_history)
    monkeypatch.setattr(common, "add_message", AsyncMock())

    async def fake_post(url, json_payload, headers, max_attempts=3, timeout=30):
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(common, "_httpx_post_with_retries", fake_post)

    asyncio.run(
        common.respond_with_personality(
            msg, "Mrazota", msg.text, reply_to=msg, reply_to_comment=msg
        )
    )
    get_thread.assert_not_awaited()
    get_history.assert_awaited_once()
