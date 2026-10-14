"""Состояния диалогов.

Диалогов четыре, все короткие: стартовый баланс, расход, ручное поступление
и корректировка. FSM держится в памяти — незаконченный диалог после
перезапуска просто начинается заново, в отличие от самих операций, которые
лежат в базе.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class StartBalance(StatesGroup):
    waiting_amount = State()
    waiting_confirm = State()


class Expense(StatesGroup):
    waiting_amount = State()
    waiting_category = State()


class ManualIncome(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class Correction(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()
