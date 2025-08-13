from pathlib import Path
import sys
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.personalities import get_mood_prompt


def test_get_mood_prompt_weights_joepeach():
    with patch("bot.personalities.random.choices") as choices_mock:
        choices_mock.return_value = ["игривое"]
        get_mood_prompt("JoePeach")
        _, kwargs = choices_mock.call_args
        assert kwargs["weights"] == [3, 3, 2, 1, 1]


def test_get_mood_prompt_weights_mrazota():
    with patch("bot.personalities.random.choices") as choices_mock:
        choices_mock.return_value = ["злое"]
        get_mood_prompt("Mrazota")
        _, kwargs = choices_mock.call_args
        assert kwargs["weights"] == [1, 1, 2, 3, 3]


def test_get_mood_prompt_unknown_personality():
    assert get_mood_prompt("Unknown") == ""
