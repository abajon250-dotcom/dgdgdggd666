from aiogram.fsm.state import State, StatesGroup

class SubmitEsim(StatesGroup):
    waiting_for_photo_and_phone = State()

class AdminSetPrice(StatesGroup):
    waiting_for_price = State()

class AdminSetSlot(StatesGroup):
    waiting_for_slot_limit = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class WithdrawState(StatesGroup):
    waiting_for_amount = State()

class TicketState(StatesGroup):
    waiting_for_category = State()
    waiting_for_message = State()

class TicketAnswer(StatesGroup):
    waiting_for_response = State()

class LanguageState(StatesGroup):
    waiting_for_lang = State()