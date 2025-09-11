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

class DummyMessage:
    def __init__(self, text="hi", chat=None, message_id=1, thread_id=0):
        self.text = text
        self.chat = chat or SimpleNamespace(id=1, type="group")
        self.message_id = message_id
        self.message_thread_id = thread_id
        self.from_user = SimpleNamespace(id=123)
        self.bot = DummyBot()
    async def reply(self, text):
        return SimpleNamespace(message_id=42)
    async def answer(self, text):
        return SimpleNamespace(message_id=43)


def test_priority_text_included(monkeypatch):
    msg = DummyMessage(text="comment text")
    monkeypatch.setattr(common, "is_group_allowed", lambda cid: True)
    monkeypatch.setattr(common, "get_thread", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "get_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "add_message", AsyncMock())

    captured = {}
    async def fake_post(url, json_payload, headers, max_attempts=3, timeout=30):
        captured['payload'] = json_payload
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(common, "_httpx_post_with_retries", fake_post)
    asyncio.run(common.respond_with_personality(msg, "Mrazota", msg.text, reply_to=msg, reply_to_comment=msg))
    messages = captured['payload']['messages']
    assert messages[-1]["content"] == msg.text
