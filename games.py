import random
import time
import json
import sqlite3
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup



import database

router = Router()

# ==================== НАСТРОЙКИ ====================
CURRENCY_NAME = "VIRTEX"
MIN_BET = 10
ADMIN_IDS = [8293927811, 8478884644]
CHANNEL_ID = "@VIRTEXCHANEL"      # КАНАЛ ДЛЯ ПРОВЕРКИ ПОДПИСКИ
CHAT_ID = "@VIRTEXCHATW"         # ЧАТ ДЛЯ ПРОВЕРКИ ПОДПИСКИ

# Банковские проценты
BANK_TERMS = {
    7: 0.03,
    14: 0.07,
    30: 0.18,
}

# Множители для игр
TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15, 8.0]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6, 4.5, 5.6, 7.0, 8.8, 11.0, 13.8, 17.3, 21.6]

# Красные числа для рулетки
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# Хранилища активных игр
TOWER_GAMES: Dict[int, Dict] = {}
DIAMOND_GAMES: Dict[int, Dict] = {}
MINES_GAMES: Dict[int, Dict] = {}

# ==================== ФОРМАТ СТАВОК (к, кк, ккк) ====================

def parse_bet(text: str) -> float:
    """Парсит ставку с поддержкой к, кк, ккк"""
    text = str(text).lower().strip().replace(" ", "")
    
    # Убираем валюту если есть
    text = text.replace("v", "").replace("i", "").replace("r", "").replace("t", "").replace("e", "").replace("x", "").replace(CURRENCY_NAME.lower(), "")
    
    multiplier = 1
    if text.endswith("ккк"):
        multiplier = 1000000000
        text = text[:-3]
    elif text.endswith("кк"):
        multiplier = 1000000
        text = text[:-2]
    elif text.endswith("к"):
        multiplier = 1000
        text = text[:-1]
    
    try:
        amount = float(text) * multiplier
        return round(amount, 2)
    except:
        raise ValueError("Неверный формат ставки")

def fmt_bet(amount: float) -> str:
    """Форматирует ставку обратно в читаемый вид"""
    amount = float(amount)
    if amount >= 1000000000 and amount % 1000000000 == 0:
        return f"{int(amount//1000000000)}ккк"
    elif amount >= 1000000 and amount % 1000000 == 0:
        return f"{int(amount//1000000)}кк"
    elif amount >= 1000 and amount % 1000 == 0:
        return f"{int(amount//1000)}к"
    return f"{amount:,.0f}".replace(",", " ")

# ==================== ПРОВЕРКА ПОДПИСКИ ====================

async def check_channel_subscription(user_id: int, bot: Bot) -> bool:
    """Проверяет подписку на канал"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except Exception:
        return False

async def check_chat_subscription(user_id: int, bot: Bot) -> bool:
    """Проверяет подписку на чат"""
    try:
        member = await bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        return member.status not in ["left", "kicked"]
    except Exception:
        return False

async def require_subscriptions(message: Message, bot: Bot) -> bool:
    """Проверяет подписку на канал и чат"""
    user_id = message.from_user.id
    user_mention = mention_user(user_id, message.from_user.first_name)
    
    in_channel = await check_channel_subscription(user_id, bot)
    in_chat = await check_chat_subscription(user_id, bot)
    
    if not in_channel and not in_chat:
        await message.answer(
            f"{user_mention}, ❌ Вы не подписаны на канал {CHANNEL_ID} и не вступили в чат {CHAT_ID}\n\n"
            f"Подпишитесь на канал и вступите в чат, чтобы играть!",
            parse_mode="HTML"
        )
        return False
    elif not in_channel:
        await message.answer(
            f"{user_mention}, ❌ Вы не подписаны на канал {CHANNEL_ID}\n\n"
            f"Подпишитесь и повторите команду!",
            parse_mode="HTML"
        )
        return False
    elif not in_chat:
        await message.answer(
            f"{user_mention}, ❌ Вы не вступили в чат {CHAT_ID}\n\n"
            f"Вступите в чат и повторите команду!",
            parse_mode="HTML"
        )
        return False
    
    return True

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def fmt_money(amount: float) -> str:
    """Форматирует число для вывода"""
    amount = round(amount, 2)
    return f"{amount:,.2f}".replace(",", " ") + f" {CURRENCY_NAME}"

def now_ts() -> int:
    return int(time.time())

def escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def mention_user(user_id: int, name: str = None) -> str:
    name = escape_html(name or f"Игрок {user_id}")
    return f'<a href="tg://user?id={user_id}">{name}</a>'

# ==================== БАНКОВСКАЯ СИСТЕМА ====================

async def get_user_balance(user_id: int) -> float:
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 0

async def update_balance(user_id: int, delta: float) -> float:
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, f"@{user_id}"))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
    new_balance = c.fetchone()[0]
    conn.close()
    return float(new_balance)

async def reserve_bet(user_id: int, amount: float) -> bool:
    balance = await get_user_balance(user_id)
    if balance < amount:
        return False
    await update_balance(user_id, -amount)
    return True

async def finalize_bet(user_id: int, payout: float) -> float:
    if payout > 0:
        return await update_balance(user_id, payout)
    return await get_user_balance(user_id)

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            code TEXT PRIMARY KEY,
            creator_id INTEGER,
            amount REAL,
            remaining INTEGER,
            created_at INTEGER,
            claimed TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    conn.close()

# ==================== ИГРА: МИНЫ (5x5, до 6 мин) ====================

def generate_mines_field(mines_count: int) -> tuple[list, list]:
    cells = list(range(25))
    mines = random.sample(cells, mines_count)
    field = [1 if i in mines else 0 for i in range(25)]
    safe = [i for i in range(25) if i not in mines]
    return field, safe

def mines_get_multiplier(opened: int, mines_count: int, total_safe: int = 19) -> float:
    if opened == 0:
        return 1.0
    safe_left = total_safe - opened
    if safe_left <= 0:
        return float('inf')
    mult = (total_safe / (total_safe - mines_count)) ** opened
    return round(mult * 0.97, 2)

def mines_keyboard(game: Dict, reveal: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in game["opened"]:
                text = "✅"
                cb = "mines_noop"
            elif reveal and idx in game["mines_set"]:
                text = "💣"
                cb = "mines_noop"
            else:
                text = "❓"
                cb = f"mines_cell_{game['user_id']}_{idx}"
            row.append(InlineKeyboardButton(text=text, callback_data=cb))
        buttons.append(row)
    
    if len(game["opened"]) > 0:
        mult = mines_get_multiplier(len(game["opened"]), game["mines_count"])
        win = int(game["bet"] * mult)
        buttons.append([InlineKeyboardButton(text=f"💰 Забрать {fmt_money(win)}", callback_data=f"mines_cash_{game['user_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"mines_cancel_{game['user_id']}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text.lower().startswith("мины "))
async def mines_start(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) < 2 or len(parts) > 3:
        return await message.answer("Формат: <code>мины 500 3</code> или <code>мины 5к 3</code>\nгде 3 — количество мин (1-6)", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    except:
        return await message.answer("Введите корректную сумму ставки (например: 500, 1к, 2кк)")
    
    mines_count = 3
    if len(parts) == 3:
        try:
            mines_count = int(parts[2])
            if mines_count < 1 or mines_count > 6:
                return await message.answer("Количество мин должно быть от 1 до 6")
        except:
            return await message.answer("Введите количество мин (1-6)")
    
    user_id = message.from_user.id
    
    if not await reserve_bet(user_id, bet):
        return await message.answer(f"❌ Недостаточно средств! Нужно: {fmt_money(bet)}")
    
    field, safe = generate_mines_field(mines_count)
    MINES_GAMES[user_id] = {
        "user_id": user_id,
        "bet": bet,
        "mines_count": mines_count,
        "field": field,
        "mines_set": set([i for i, v in enumerate(field) if v == 1]),
        "opened": set(),
        "safe_list": safe
    }
    
    await message.answer(
        f"💣 <b>Игра МИНЫ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Мин на поле: {mines_count}\n"
        f"Безопасных клеток: {25 - mines_count}\n\n"
        f"Открывайте клетки!",
        reply_markup=mines_keyboard(MINES_GAMES[user_id]),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("mines_cell_"))
async def mines_cell(call: CallbackQuery, bot: Bot):
    user_id = call.from_user.id
    if user_id != int(call.data.split("_")[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = MINES_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    cell = int(call.data.split("_")[3])
    
    if cell in game["opened"]:
        return await call.answer("Клетка уже открыта", show_alert=True)
    
    if cell in game["mines_set"]:
        await call.answer("💥 БОМБА! Вы проиграли!", show_alert=True)
        await finalize_bet(user_id, 0)
        MINES_GAMES.pop(user_id, None)
        await call.message.edit_text(
            f"💣 <b>Игра МИНЫ</b>\n\n"
            f"Вы наткнулись на мину!\n"
            f"Ставка сгорела: {fmt_money(game['bet'])}",
            reply_markup=mines_keyboard(game, reveal=True),
            parse_mode="HTML"
        )
        return
    
    game["opened"].add(cell)
    
    if len(game["opened"]) == len(game["safe_list"]):
        mult = mines_get_multiplier(len(game["opened"]), game["mines_count"])
        win = int(game["bet"] * mult)
        await finalize_bet(user_id, win)
        await call.message.edit_text(
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"Все безопасные клетки открыты!\n"
            f"Выигрыш: {fmt_money(win)}",
            reply_markup=mines_keyboard(game, reveal=True),
            parse_mode="HTML"
        )
        MINES_GAMES.pop(user_id, None)
        return
    
    await call.message.edit_text(
        f"💣 <b>Игра МИНЫ</b>\n\n"
        f"✅ Безопасно!\n"
        f"Осталось клеток: {len(game['safe_list']) - len(game['opened'])}\n"
        f"Текущий множитель: x{mines_get_multiplier(len(game['opened']), game['mines_count'])}",
        reply_markup=mines_keyboard(game),
        parse_mode="HTML"
    )
    await call.answer("✅ Безопасно!")

@router.callback_query(F.data.startswith("mines_cash_"))
async def mines_cash(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id != int(call.data.split("_")[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = MINES_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    mult = mines_get_multiplier(len(game["opened"]), game["mines_count"])
    win = int(game["bet"] * mult)
    await finalize_bet(user_id, win)
    MINES_GAMES.pop(user_id, None)
    
    await call.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n\n"
        f"Вы получили: {fmt_money(win)}",
        parse_mode="HTML"
    )
    await call.answer(f"Выигрыш {fmt_money(win)} зачислен!", show_alert=True)

@router.callback_query(F.data.startswith("mines_cancel_"))
async def mines_cancel(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id != int(call.data.split("_")[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = MINES_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    await finalize_bet(user_id, game["bet"])
    MINES_GAMES.pop(user_id, None)
    
    await call.message.edit_text(
        f"❌ Игра отменена.\n\nСтавка возвращена: {fmt_money(game['bet'])}",
        parse_mode="HTML"
    )
    await call.answer("Игра отменена")

@router.callback_query(F.data == "mines_noop")
async def mines_noop(call: CallbackQuery):
    await call.answer()

# ==================== ИГРА: БАШНЯ ====================

def tower_multiplier(level: int, mines: int) -> float:
    if level == 0:
        return 1.0
    p = (5 - mines) / 5
    if p <= 0:
        return 0
    fair = 1 / (p ** level)
    return round(min(fair * 0.97, 1000), 2)

def tower_keyboard(game: Dict) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for j in range(5):
        row.append(InlineKeyboardButton(text="❔", callback_data=f"tower_pick_{game['user_id']}_{j}"))
    buttons.append(row)
    
    if game["level"] > 0:
        mult = tower_multiplier(game["level"], game["mines"])
        win = int(game["bet"] * mult)
        buttons.append([InlineKeyboardButton(text=f"💰 Забрать {fmt_money(win)}", callback_data=f"tower_cash_{game['user_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"tower_cancel_{game['user_id']}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text.lower().startswith("башня "))
async def tower_start(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) < 2 or len(parts) > 3:
        return await message.answer("Формат: <code>башня 500 2</code> или <code>башня 1к 2</code>\nгде 2 — количество мин в ряду (1-4)", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    mines = 1
    if len(parts) == 3:
        try:
            mines = int(parts[2])
            if mines < 1 or mines > 4:
                return await message.answer("Мин в ряду: от 1 до 4")
        except:
            return await message.answer("Введите количество мин (1-4)")
    
    user_id = message.from_user.id
    
    if not await reserve_bet(user_id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    TOWER_GAMES[user_id] = {
        "user_id": user_id,
        "bet": bet,
        "mines": mines,
        "level": 0,
        "selected": [],
        "bombs": [random.sample(range(5), mines) for _ in range(9)]
    }
    
    await message.answer(
        f"🗼 <b>Игра БАШНЯ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Мин в ряду: {mines}\n"
        f"Уровней: 9\n\n"
        f"Выберите безопасную ячейку!",
        reply_markup=tower_keyboard(TOWER_GAMES[user_id]),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("tower_pick_"))
async def tower_pick(call: CallbackQuery):
    parts = call.data.split("_")
    user_id = call.from_user.id
    if user_id != int(parts[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    choice = int(parts[3])
    level = game["level"]
    
    if choice in game["bombs"][level]:
        await finalize_bet(user_id, 0)
        TOWER_GAMES.pop(user_id, None)
        await call.message.edit_text(
            f"💥 <b>Игра БАШНЯ</b>\n\n"
            f"Вы наткнулись на мину на уровне {level + 1}!\n"
            f"Ставка сгорела: {fmt_money(game['bet'])}",
            parse_mode="HTML"
        )
        await call.answer("💥 Вы проиграли!", show_alert=True)
        return
    
    game["selected"].append(choice)
    game["level"] += 1
    
    if game["level"] >= 9:
        mult = tower_multiplier(9, game["mines"])
        win = int(game["bet"] * mult)
        await finalize_bet(user_id, win)
        TOWER_GAMES.pop(user_id, None)
        await call.message.edit_text(
            f"🎉 <b>ПОБЕДА! БАШНЯ ПРОЙДЕНА!</b>\n\n"
            f"Выигрыш: {fmt_money(win)}",
            parse_mode="HTML"
        )
        return
    
    await call.message.edit_text(
        f"🗼 <b>Игра БАШНЯ</b>\n\n"
        f"✅ Уровень {game['level']} пройден!\n"
        f"Текущий множитель: x{tower_multiplier(game['level'], game['mines'])}\n"
        f"Потенциальный выигрыш: {fmt_money(int(game['bet'] * tower_multiplier(game['level'], game['mines'])))}",
        reply_markup=tower_keyboard(game),
        parse_mode="HTML"
    )
    await call.answer("✅ Уровень пройден!")

@router.callback_query(F.data.startswith("tower_cash_"))
async def tower_cash(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id != int(call.data.split("_")[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    mult = tower_multiplier(game["level"], game["mines"])
    win = int(game["bet"] * mult)
    await finalize_bet(user_id, win)
    TOWER_GAMES.pop(user_id, None)
    
    await call.message.edit_text(
        f"💰 <b>Выигрыш забран!</b>\n\n"
        f"Вы получили: {fmt_money(win)}",
        parse_mode="HTML"
    )
    await call.answer(f"Выигрыш {fmt_money(win)} зачислен!", show_alert=True)

@router.callback_query(F.data.startswith("tower_cancel_"))
async def tower_cancel(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id != int(call.data.split("_")[2]):
        return await call.answer("Это не ваша игра!", show_alert=True)
    
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await call.answer("Игра не найдена", show_alert=True)
    
    await finalize_bet(user_id, game["bet"])
    TOWER_GAMES.pop(user_id, None)
    
    await call.message.edit_text(
        f"❌ Игра отменена.\n\nСтавка возвращена: {fmt_money(game['bet'])}",
        parse_mode="HTML"
    )
    await call.answer("Игра отменена")

# ==================== ИГРА: КРАШ ====================

@router.message(F.text.lower().startswith("краш "))
async def crash_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: <code>краш 500 2.5</code> или <code>краш 1к 2.5</code>", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
        target = float(parts[2].replace(",", "."))
        if target < 1.1 or target > 10:
            return await message.answer("Множитель должен быть от 1.1 до 10")
    except:
        return await message.answer("Введите корректные данные")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    crash_mult = random.uniform(1.0, 20.0)
    if crash_mult > 15:
        crash_mult = 15.0
    
    win = target <= crash_mult
    payout = int(bet * target) if win else 0
    
    await finalize_bet(message.from_user.id, payout)
    
    await message.answer(
        f"📈 <b>КРАШ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Твой множитель: x{target:.2f}\n"
        f"Множитель игры: x{crash_mult:.2f}\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== ИГРА: КУБИК ====================

@router.message(F.text.lower().startswith("кубик "))
async def cube_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: <code>кубик 500 5</code> или <code>кубик 1к чет</code>", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    guess = parts[2].lower()
    dice = random.randint(1, 6)
    
    win = False
    mult = 1.0
    
    if guess == str(dice):
        win, mult = True, 3.5
    elif guess in ["чет", "even"] and dice % 2 == 0:
        win, mult = True, 1.9
    elif guess in ["нечет", "odd"] and dice % 2 == 1:
        win, mult = True, 1.9
    elif guess in ["б", "more"] and dice >= 4:
        win, mult = True, 1.9
    elif guess in ["м", "less"] and dice <= 3:
        win, mult = True, 1.9
    
    payout = int(bet * mult) if win else 0
    await finalize_bet(message.from_user.id, payout)
    
    await message.answer(
        f"🎲 <b>КУБИК</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Выпало число: <b>{dice}</b>\n"
        f"Ваша ставка: {guess}\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== ИГРА: КОСТИ ====================

@router.message(F.text.lower().startswith("кости "))
async def dice_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: <code>кости 500 м</code> или <code>кости 1к равно</code>\nгде: м (меньше 7), б (больше 7), равно", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    choice = parts[2].lower()
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    win = False
    mult = 1.0
    
    if choice in ["м", "less"] and total < 7:
        win, mult = True, 2.25
    elif choice in ["б", "more"] and total > 7:
        win, mult = True, 2.25
    elif choice in ["равно", "equal", "7"] and total == 7:
        win, mult = True, 5.0
    
    payout = int(bet * mult) if win else 0
    await finalize_bet(message.from_user.id, payout)
    
    relation = "меньше 7" if total < 7 else ("больше 7" if total > 7 else "равно 7")
    
    await message.answer(
        f"🎯 <b>КОСТИ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Выпало: <b>{dice1}</b> + <b>{dice2}</b> = <b>{total}</b> ({relation})\n"
        f"Ваша ставка: {choice}\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== ИГРА: РУЛЕТКА ====================

@router.message(F.text.lower().startswith("рул "))
async def roulette_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: <code>рул 500 чет</code> или <code>рул 1к кра</code>\n"
                                   "Ставки: кра (красное), чер (черное), чет, нечет, зеро", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    choice = parts[2].lower()
    number = random.randint(0, 36)
    
    if number == 0:
        color = "green"
        parity = "zero"
    elif number in RED_NUMBERS:
        color = "red"
        parity = "even" if number % 2 == 0 else "odd"
    else:
        color = "black"
        parity = "even" if number % 2 == 0 else "odd"
    
    win = False
    mult = 2.0
    
    if choice in ["кра", "red"] and color == "red":
        win = True
    elif choice in ["чер", "black"] and color == "black":
        win = True
    elif choice in ["чет", "even"] and parity == "even":
        win = True
    elif choice in ["нечет", "odd"] and parity == "odd":
        win = True
    elif choice in ["зеро", "zero"] and number == 0:
        win, mult = True, 36.0
    
    payout = int(bet * mult) if win else 0
    await finalize_bet(message.from_user.id, payout)
    
    color_text = {"red": "🔴 красное", "black": "⚫ черное", "green": "🟢 зеро"}[color]
    
    await message.answer(
        f"🎡 <b>РУЛЕТКА</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Выпало: <b>{number}</b> ({color_text})\n"
        f"Ваша ставка: {choice}\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== ИГРА: ФУТБОЛ ====================

@router.message(F.text.lower().startswith("футбол "))
async def football_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("Формат: <code>футбол 500 гол</code> или <code>футбол 1к мимо</code>", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    choice = parts[2].lower()
    value = random.randint(1, 6)
    result = "гол" if value >= 4 else "мимо"
    
    win = result == choice
    payout = int(bet * 1.85) if win else 0
    
    await finalize_bet(message.from_user.id, payout)
    
    await message.answer(
        f"⚽ <b>ФУТБОЛ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Результат удара: <b>{result.upper()}</b>\n"
        f"Ваша ставка: {choice}\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== ИГРА: БАСКЕТБОЛ ====================

@router.message(F.text.lower().startswith("баскет "))
async def basket_game(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Формат: <code>баскет 500</code> или <code>баскет 1к</code>", parse_mode="HTML")
    
    try:
        bet = parse_bet(parts[1])
    except:
        return await message.answer("Введите корректную сумму ставки")
    
    if bet < MIN_BET:
        return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
    
    if not await reserve_bet(message.from_user.id, bet):
        return await message.answer(f"❌ Недостаточно средств!")
    
    value = random.randint(1, 6)
    win = value >= 4
    payout = int(bet * 2.2) if win else 0
    
    await finalize_bet(message.from_user.id, payout)
    
    result_text = "ТОЧНЫЙ БРОСОК! 🏀" if win else "ПРОМАХ! ❌"
    
    await message.answer(
        f"🏀 <b>БАСКЕТБОЛ</b>\n\n"
        f"Ставка: {fmt_money(bet)}\n"
        f"Результат: <b>{result_text}</b>\n"
        f"Результат: {'✅ ПОБЕДА' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"Выигрыш: {fmt_money(payout)}",
        parse_mode="HTML"
    )

# ==================== БАНКОВСКАЯ СИСТЕМА ====================

class BankStates(StatesGroup):
    waiting_amount = State()

@router.message(Command("банк"))
async def bank_menu(message: Message, bot: Bot):
    if not await require_subscriptions(message, bot):
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank_open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank_list")],
        [InlineKeyboardButton(text="💰 Снять депозиты", callback_data="bank_withdraw")]
    ])
    
    await message.answer(
        f"🏦 <b>БАНКОВСКАЯ СИСТЕМА</b>\n\n"
        f"Депозиты в VIRTEX:\n"
        f"• 7 дней — +3%\n"
        f"• 14 дней — +7%\n"
        f"• 30 дней — +18%\n\n"
        f"<i>Проценты начисляются в конце срока в VIRTEX!</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "bank_open")
async def bank_open(call: CallbackQuery, state: FSMContext):
    await state.set_state(BankStates.waiting_amount)
    await call.message.answer("💰 Введите сумму депозита в VIRTEX (минимум 100):\n\nПример: <code>1000</code> или <code>1к</code>", parse_mode="HTML")
    await call.answer()

@router.message(BankStates.waiting_amount)
async def bank_amount(message: Message, state: FSMContext):
    try:
        amount = parse_bet(message.text)
        if amount < 100:
            return await message.answer("❌ Минимальная сумма депозита: 100 VIRTEX")
    except:
        return await message.answer("❌ Введите корректную сумму в VIRTEX")
    
    await state.update_data(amount=amount)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней (+3%)", callback_data="bank_term_7")],
        [InlineKeyboardButton(text="14 дней (+7%)", callback_data="bank_term_14")],
        [InlineKeyboardButton(text="30 дней (+18%)", callback_data="bank_term_30")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bank_cancel")]
    ])
    
    await message.answer(
        f"📅 Выберите срок депозита для суммы {fmt_money(amount)}:",
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
    
    if not await reserve_bet(call.from_user.id, amount):
        await call.message.answer("❌ Недостаточно VIRTEX на балансе!")
        await state.clear()
        return
    
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO bank_deposits (user_id, amount, term_days, rate, created_at, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """, (call.from_user.id, amount, days, rate, now_ts()))
    conn.commit()
    conn.close()
    
    payout = amount * (1 + rate)
    await call.message.edit_text(
        f"✅ <b>Депозит открыт!</b>\n\n"
        f"Сумма: {fmt_money(amount)}\n"
        f"Срок: {days} дней\n"
        f"Доходность: +{int(rate*100)}%\n"
        f"Вы получите: {fmt_money(payout)}\n\n"
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
    c.execute("SELECT id, amount, term_days, rate, created_at, status FROM bank_deposits WHERE user_id = ? ORDER BY id DESC", (call.from_user.id,))
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
        text += f"#{id_}: {fmt_money(amount)} на {days}д (+{int(rate*100)}%) — {status_text}\n"
    
    await call.message.edit_text(text, parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data == "bank_withdraw")
async def bank_withdraw(call: CallbackQuery):
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, amount, term_days, rate, created_at FROM bank_deposits WHERE user_id = ? AND status = 'active'", (call.from_user.id,))
    rows = c.fetchall()
    
    withdrawn = 0
    now = now_ts()
    for row in rows:
        id_, amount, days, rate, created = row
        expires = created + days * 86400
        if now >= expires:
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

# ==================== КОМАНДА ВЫДАЧИ ВАЛЮТЫ ====================

@router.message(F.text.lower().startswith("выдать "))
async def admin_give_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("⛔ Команда только для администраторов!")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Формат: <code>выдать 1000</code> или <code>выдать 5к</code>", parse_mode="HTML")
    
    try:
        amount = parse_bet(parts[1])
        if amount <= 0:
            raise ValueError
    except:
        return await message.answer("Введите корректную сумму")
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
    else:
        target = message.from_user
    
    await update_balance(target.id, amount)
    
    await message.answer(
        f"✅ Выдано {fmt_money(amount)} пользователю {mention_user(target.id, target.first_name)}",
        parse_mode="HTML"
    )

# ==================== ТОП ЧАТА И МИРОВОЙ ТОП ====================

@router.message(Command("topchat"))
async def top_chat_command(message: Message, bot: Bot):
    """Топ пользователей в этом чате"""
    if not await require_subscriptions(message, bot):
        return
    
    chat_id = message.chat.id
    
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, name, balance FROM users 
        WHERE balance > 0 
        ORDER BY balance DESC 
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return await message.answer("📭 Список богачей пока пуст!")
    
    text = "🏆 <b>ТОП-10 В ЭТОМ ЧАТЕ</b>\n\n"
    for i, (user_id, name, balance) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        name = escape_html(name or "Игрок")
        text += f"{medal} {name} — {fmt_money(balance)}\n"
    
    await message.answer(text, parse_mode="HTML")

@router.message(Command("top"))
async def top_global_command(message: Message, bot: Bot):
    """Мировой топ пользователей"""
    if not await require_subscriptions(message, bot):
        return
    
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, name, balance FROM users 
        WHERE balance > 0 
        ORDER BY balance DESC 
        LIMIT 30
    """)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return await message.answer("📭 Список богачей пока пуст!")
    
    text = "🌍 <b>МИРОВОЙ ТОП-30</b>\n\n"
    for i, (user_id, name, balance) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        name = escape_html(name or "Игрок")
        text += f"{medal} {name} — {fmt_money(balance)}\n"
    
    await message.answer(text, parse_mode="HTML")

# ==================== ИНИЦИАЛИЗАЦИЯ ====================

init_bank_tables()
