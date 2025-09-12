import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common
from bot.config import ADMIN_ID


class DummyChat:
    def __init__(self, id=1):
        self.id = id


class DummyMessage:
    def __init__(self, text="", from_user=None, reply_to_message=None, chat=None, bot=None):
        self.text = text
        self.from_user = from_user
        self.reply_to_message = reply_to_message
        self.chat = chat or DummyChat()
        self.bot = bot
        self.message_id = 1
        self.message_thread_id = 0

    async def delete(self):
        pass


def test_cmd_ban_adds_user(monkeypatch):
    admin = SimpleNamespace(id=ADMIN_ID)
    target = SimpleNamespace(id=123)
    reply = SimpleNamespace(from_user=target)
    msg = DummyMessage(text="/ban", from_user=admin, reply_to_message=reply)
    add_mock = AsyncMock()
    monkeypatch.setattr(common, "add_banned_user", add_mock)
    asyncio.run(common.cmd_ban(msg))
    add_mock.assert_awaited_once_with(target.id)


def test_handle_message_skips_banned(monkeypatch):
    user = SimpleNamespace(id=55, is_bot=False, full_name="User")
    msg = DummyMessage(text="hi", from_user=user)
    monkeypatch.setattr(common, "is_group_allowed", lambda chat_id: True)
    monkeypatch.setattr(common, "is_banned", AsyncMock(return_value=True))
    add_message_mock = AsyncMock()
    monkeypatch.setattr(common, "add_message", add_message_mock)
    asyncio.run(common.handle_message(msg, "Mrazota"))
    add_message_mock.assert_not_awaited()
