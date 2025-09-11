import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common

class DummyBot:
    async def send_chat_action(self, chat_id, action):
        pass

sent_to = []

class DummyMessage:
    def __init__(self, msg_id, text="", reply_to_message=None):
        self.text = text
        self.chat = SimpleNamespace(id=1, type="group")
        self.message_id = msg_id
        self.message_thread_id = 0
        self.from_user = SimpleNamespace(id=123)
        self.bot = DummyBot()
        self.reply_to_message = reply_to_message
    async def reply(self, text):
        sent_to.append((self, text))
        return SimpleNamespace(message_id=100 + len(sent_to))
    async def answer(self, text):
        sent_to.append((self, text))
        return SimpleNamespace(message_id=200 + len(sent_to))


def test_followup_messages_reply_to_post(monkeypatch):
    post = DummyMessage(10, "post")
    comment = DummyMessage(20, "comment", reply_to_message=post)
    monkeypatch.setattr(common, "is_group_allowed", lambda cid: True)
    monkeypatch.setattr(common, "get_thread", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "get_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common.asyncio, "sleep", AsyncMock())

    async def fake_post(url, json_payload, headers, max_attempts=3, timeout=30):
        return {"choices": [{"message": {"content": "first</br>second"}}]}

    monkeypatch.setattr(common, "_httpx_post_with_retries", fake_post)

    asyncio.run(common.respond_with_personality(comment, "Mrazota", comment.text, reply_to=comment, reply_to_comment=comment))

    assert sent_to[0][0] is comment
    assert sent_to[0][1] == "first"
    assert sent_to[1][0] is post
    assert sent_to[1][1] == "second"
