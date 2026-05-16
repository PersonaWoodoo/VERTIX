import random
import string
import time
import asyncio
import sqlite3
from typing import Dict

import database
from games.config import CURRENCY_NAME


# ==================== ФОРМАТИРОВАНИЕ ====================

def fmt_money(amount: float) -> str:
    amount = round(amount, 2)
    if amount >= 1_000_000_000:
        return f"{amount/1_000_000_000:.1f}ккк {CURRENCY_NAME}"
    if amount >= 1_000_000:
        return f"{amount/1_000_000:.1f}кк {CURRENCY_NAME}"
    if amount >= 1_000:
        return f"{amount/1_000:.1f}к {CURRENCY_NAME}"
    return f"{amount:.0f} {CURRENCY_NAME}"


def parse_bet(text: str) -> float:
    text = str(text).lower().strip().replace(" ", "")
    multiplier = 1
    if text.endswith("ккк"):
        multiplier = 1_000_000_000
        text = text[:-3]
    elif text.endswith("кк"):
        multiplier = 1_000_000
        text = text[:-2]
    elif text.endswith("к"):
        multiplier = 1_000
        text = text[:-1]
    try:
        return round(float(text) * multiplier, 2)
    except Exception:
        raise ValueError("Неверный формат ставки")


def now_ts() -> int:
    return int(time.time())


def escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mention_user(user_id: int, name: str = None) -> str:
    name = escape_html(name or f"Игрок {user_id}")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def _new_gid(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


# ==================== БЛОКИРОВКИ ИГР ====================

user_game_locks: Dict[str, asyncio.Lock] = {}


def _game_lock(user_id: int) -> asyncio.Lock:
    key = str(user_id)
    if key not in user_game_locks:
        user_game_locks[key] = asyncio.Lock()
    return user_game_locks[key]


# ==================== БАЛАНС ====================

async def get_balance(user_id: int) -> float:
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else 100


async def update_balance(user_id: int, delta: float) -> float:
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, f"@{user_id}"))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
    new_balance = c.fetchone()[0]
    conn.close()
    return float(new_balance)


async def reserve_bet(user_id: int, amount: float) -> tuple[bool, float]:
    balance = await get_balance(user_id)
    if balance < amount:
        return False, balance
    new_balance = await update_balance(user_id, -amount)
    return True, new_balance


async def finalize_bet(user_id: int, bet: float, payout: float, choice: str, outcome: str) -> float:
    if payout > 0:
        return await update_balance(user_id, payout)
    return await get_balance(user_id)


def add_balance(user_id: int, delta: float) -> float:
    conn = sqlite3.connect(database.DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, f"@{user_id}"))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
    new_balance = c.fetchone()[0]
    conn.close()
    return float(new_balance)
