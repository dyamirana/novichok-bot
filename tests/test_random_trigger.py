from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers.common import should_count_for_random


class DummyChat:
    def __init__(self, type_):
        self.type = type_


class DummyMessage:
    def __init__(self, chat_type, text):
        self.chat = DummyChat(chat_type)
        self.text = text


def test_should_count_private():
    msg = DummyMessage("private", "hello world" * 2)
    assert should_count_for_random(msg, "JoePeach")


def test_should_count_group():
    msg = DummyMessage("group", "hello world" * 2)
    assert should_count_for_random(msg, "JoePeach")


def test_should_not_count_channel():
    msg = DummyMessage("channel", "hello world" * 2)
    assert not should_count_for_random(msg, "JoePeach")


def test_should_not_count_short_text():
    msg = DummyMessage("private", "hi")
    assert not should_count_for_random(msg, "JoePeach")


def test_should_not_count_other_personality():
    msg = DummyMessage("private", "hello world" * 2)
    assert not should_count_for_random(msg, "Kuplinov")
