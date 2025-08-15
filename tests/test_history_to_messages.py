import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers.common import _history_to_messages


def test_history_to_messages_adds_name_to_content():
    history = [
        {"role": "user", "content": "привет", "name": "Вася"},
        {"role": "assistant", "content": "привет", "name": "Бот"},
    ]
    msgs = _history_to_messages("sys", history)
    assert msgs[1]["content"] == "Вася: привет"
    assert msgs[1]["name"] == "Вася"
    assert msgs[2]["content"] == "Бот: привет"
    assert msgs[2]["name"] == "Бот"


def test_history_to_messages_without_name():
    history = [{"role": "user", "content": "hi"}]
    msgs = _history_to_messages("sys", history)
    assert msgs[1] == {"role": "user", "content": "hi"}
