import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.handlers.common import _build_prompt


def test_build_prompt_combines_priority_and_context():
    system, user = _build_prompt(
        "JoePeach", "ctx line1\nctx line2", "priority message", ""
    )
    assert "Сначала идет сообщение пользователя" in system
    assert user.startswith("priority message")
    assert "ctx line1" in user
    assert "ctx line2" in user


def test_build_prompt_only_context_when_no_priority():
    system, user = _build_prompt("JoePeach", "ctx only", "", "")
    assert user == "ctx only"
