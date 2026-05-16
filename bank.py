import time
import sqlite3

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

import database
from games import fmt_money, parse_bet, update_balance, reserve_bet

router = Router()

# Банковские проценты
BANK_TERMS = {
    7: 0.03,
    14: 0.07,
    30: 0.18,
}

def now_ts() -> int:
    return int(time.time())


# ==================== ИНИЦИАЛИЗАЦИЯ ====================

def init_bank_tables():
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bank_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            term_days INTEGER,
            rate REAL,
            created_at INTEGER,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()


# ==================== СОСТОЯНИЯ ====================

class BankStates(StatesGroup):
    waiting_amount = State()


# ==================== ХЕНДЛЕРЫ ====================

@router.message(Command("банк"))
async def bank_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank_open")],
        [InlineKeyboardButton(text="📜 Мои депозиты",    callback_data="bank_list")],
        [InlineKeyboardButton(text="💰 Снять депозиты",  callback_data="bank_withdraw")],
    ])
    await message.answer(
        "🏦 <b>БАНКОВСКАЯ СИСТЕМА</b>\n\n"
        "Депозиты в VIRTEX:\n"
        "• 7 дней — +3%\n"
        "• 14 дней — +7%\n"
        "• 30 дней — +18%\n\n"
        "<i>Проценты начисляются в конце срока в VIRTEX!</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "bank_open")
async def bank_open(call: CallbackQuery, state: FSMContext):
    await state.set_state(BankStates.waiting_amount)
    await call.message.answer(
        "💰 Введите сумму депозита в VIRTEX (минимум 100 VIRTEX):\n\nПример: <code>1000</code> или <code>1к</code>",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(BankStates.waiting_amount)
async def bank_amount(message: Message, state: FSMContext):
    try:
        amount = parse_bet(message.text)
        if amount < 100:
            return await message.answer("❌ Минимальная сумма депозита: 100 VIRTEX")
    except Exception:
        return await message.answer("❌ Введите корректную сумму в VIRTEX")

    await state.update_data(amount=amount)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней (+3%)",   callback_data="bank_term_7")],
        [InlineKeyboardButton(text="14 дней (+7%)",  callback_data="bank_term_14")],
        [InlineKeyboardButton(text="30 дней (+18%)", callback_data="bank_term_30")],
        [InlineKeyboardButton(text="❌ Отмена",       callback_data="bank_cancel")],
    ])
    await message.answer(
        f"📅 Выберите срок депозита для суммы {fmt_money(amount)} VIRTEX:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("bank_term_"))
async def bank_term(call: CallbackQuery, state: FSMContext):
    days = int(call.data.split("_")[2])
    data = await state.get_data()
    amount = data.get("amount", 0)

    if amount < 100:
        await call.message.answer("❌ Минимальная сумма депозита 100 VIRTEX")
        await state.clear()
        return

    rate = BANK_TERMS[days]
    ok = await reserve_bet(call.from_user.id, amount)
    if not ok:
        await call.message.answer("❌ Недостаточно VIRTEX на балансе!")
        await state.clear()
        return

    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO bank_deposits (user_id, amount, term_days, rate, created_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
        (call.from_user.id, amount, days, rate, now_ts())
    )
    conn.commit()
    conn.close()

    payout = amount * (1 + rate)
    await call.message.edit_text(
        f"✅ <b>Депозит открыт!</b>\n\n"
        f"Сумма: {fmt_money(amount)} VIRTEX\n"
        f"Срок: {days} дней\n"
        f"Доходность: +{int(rate * 100)}%\n"
        f"Вы получите: {fmt_money(payout)} VIRTEX\n\n"
        f"<i>VIRTEX будут доступны для вывода после окончания срока</i>",
        parse_mode="HTML"
    )
    await state.clear()
    await call.answer()


@router.callback_query(F.data == "bank_cancel")
async def bank_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Операция отменена")
    await call.answer()


@router.callback_query(F.data == "bank_list")
async def bank_list(call: CallbackQuery):
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, amount, term_days, rate, created_at, status FROM bank_deposits WHERE user_id = ? ORDER BY id DESC",
        (call.from_user.id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await call.message.answer("📭 У вас нет депозитов в VIRTEX")
        return

    text = "📜 <b>Ваши депозиты в VIRTEX:</b>\n\n"
    now = now_ts()
    for row in rows:
        id_, amount, days, rate, created, status = row
        expires = created + days * 86400
        if status == "active" and now >= expires:
            status = "ready"
        status_text = "✅ Готов к выводу" if status == "ready" else "⏳ Активен"
        text += f"#{id_}: {fmt_money(amount)} VIRTEX на {days}д (+{int(rate * 100)}%) — {status_text}\n"

    await call.message.edit_text(text, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "bank_withdraw")
async def bank_withdraw(call: CallbackQuery):
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, amount, term_days, rate, created_at FROM bank_deposits WHERE user_id = ? AND status = 'active'",
        (call.from_user.id,)
    )
    rows = c.fetchall()

    withdrawn = 0.0
    now = now_ts()
    for row in rows:
        id_, amount, days, rate, created = row
        if now >= created + days * 86400:
            payout = amount * (1 + rate)
            await update_balance(call.from_user.id, payout)
            c.execute("UPDATE bank_deposits SET status = 'closed' WHERE id = ?", (id_,))
            withdrawn += payout

    conn.commit()
    conn.close()

    if withdrawn > 0:
        await call.message.edit_text(f"✅ Выведено VIRTEX: {fmt_money(withdrawn)}", parse_mode="HTML")
    else:
        await call.message.edit_text("📭 Нет депозитов, готовых к выводу VIRTEX")
    await call.answer()


init_bank_tables()
