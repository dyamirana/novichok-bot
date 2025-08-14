from aiogram.fsm.state import State, StatesGroup


class GreetingState(StatesGroup):
    waiting = State()


class QuestionState(StatesGroup):
    waiting = State()


class ButtonAddState(StatesGroup):
    waiting_label = State()
    waiting_response = State()


class ButtonEditState(StatesGroup):
    waiting_response = State()


class KuplinovAddState(StatesGroup):
    waiting_id = State()


class KuplinovDelState(StatesGroup):
    waiting_id = State()


class PersonalityEditState(StatesGroup):
    waiting_text = State()
