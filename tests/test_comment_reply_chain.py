import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers import common

sent_actions = []


class DummyBot:
    async def send_chat_action(self, chat_id, action):
        pass

    async def send_message(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        sent_actions.append(
            (
                "send_message",
                chat_id,
                text,
                {
                    "reply_to_message_id": reply_to_message_id,
                    "message_thread_id": message_thread_id,
                },
            )
        )
        return SimpleNamespace(message_id=300 + len(sent_actions))


class DummyMessage:
    def __init__(self, msg_id, text="", reply_to_message=None, thread_id=None):
        self.text = text
        self.chat = SimpleNamespace(id=1, type="group")
        self.message_id = msg_id
        self.message_thread_id = thread_id if thread_id is not None else msg_id
        self.from_user = SimpleNamespace(id=123)
        self.bot = DummyBot()
        self.reply_to_message = reply_to_message

    async def reply(self, text):
        sent_actions.append(("reply", self, text))
        return SimpleNamespace(message_id=100 + len(sent_actions))

    async def answer(self, text):
        sent_actions.append(("answer", self, text))
        return SimpleNamespace(message_id=200 + len(sent_actions))


def test_followup_messages_reply_to_post(monkeypatch):
    sent_actions.clear()
    post = DummyMessage(10, "post", thread_id=10)
    comment = DummyMessage(20, "comment", reply_to_message=post, thread_id=10)
    monkeypatch.setattr(common, "is_group_allowed", lambda cid: True)
    monkeypatch.setattr(common, "get_thread", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "get_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common.asyncio, "sleep", AsyncMock())

    async def fake_post(url, json_payload, headers, max_attempts=3, timeout=30):
        return {"choices": [{"message": {"content": "first</br>second"}}]}

    monkeypatch.setattr(common, "_httpx_post_with_retries", fake_post)

    asyncio.run(common.respond_with_personality(comment, "Mrazota", comment.text, reply_to=comment, reply_to_comment=comment))

    assert sent_actions[0] == ("reply", comment, "first")
    method, chat_id, text, kwargs = sent_actions[1]
    assert method == "send_message"
    assert chat_id == comment.chat.id
    assert text == "second"
    assert kwargs == {
        "reply_to_message_id": comment.message_id,
        "message_thread_id": comment.message_thread_id,
    }


def test_followup_when_replying_to_bot_comment(monkeypatch):
    sent_actions.clear()
    post = DummyMessage(10, "post", thread_id=10)
    bot_comment = DummyMessage(15, "bot", reply_to_message=post, thread_id=10)
    user_reply = DummyMessage(20, "reply", reply_to_message=bot_comment, thread_id=10)
    monkeypatch.setattr(common, "is_group_allowed", lambda cid: True)
    monkeypatch.setattr(common, "get_thread", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "get_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(common, "add_message", AsyncMock())
    monkeypatch.setattr(common.asyncio, "sleep", AsyncMock())

    async def fake_post(url, json_payload, headers, max_attempts=3, timeout=30):
        return {"choices": [{"message": {"content": "first</br>second"}}]}

    monkeypatch.setattr(common, "_httpx_post_with_retries", fake_post)

    asyncio.run(common.respond_with_personality(user_reply, "Mrazota", user_reply.text, reply_to=user_reply, reply_to_comment=user_reply))

    assert sent_actions[0] == ("reply", user_reply, "first")
    method, chat_id, text, kwargs = sent_actions[1]
    assert method == "send_message"
    assert chat_id == user_reply.chat.id
    assert text == "second"
    assert kwargs == {
        "reply_to_message_id": user_reply.message_id,
        "message_thread_id": user_reply.message_thread_id,
    }
