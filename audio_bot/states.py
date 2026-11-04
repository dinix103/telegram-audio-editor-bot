from aiogram.fsm.state import State, StatesGroup


class Editor(StatesGroup):
    text = State()
    cover = State()
