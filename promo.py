import asyncio
import aiosqlite
import database
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database import DB_PATH

router = Router()

ADMIN_IDS = [8293927811, 8478884644]

# Глобальный лок для защиты от "database is locked"
db_lock = asyncio.Lock()


# --- КОМАНДА ДЛЯ АДМИНОВ ---
@router.message(F.text.lower().startswith("/создать"))
async def cmd_create_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) < 4:
        return await message.reply("❌ <b>Формат:</b> <code>/Создать #текст (сумма) (активации)</code>",
                                   parse_mode="HTML")

    code = args[1].lower()
    try:
        amount = int(args[2])
        uses = int(args[3])
    except ValueError:
        return await message.reply("❌ Сумма и активации должны быть числами!")

    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL;")

            async with db.execute("SELECT code FROM promos WHERE code = ?", (code,)) as cur:
                if await cur.fetchone():
                    return await message.reply("❌ Промокод уже существует!")

            await db.execute(
                "INSERT INTO promos (code, amount, max_uses, current_uses) VALUES (?, ?, ?, ?)",
                (code, amount, uses, 0)
            )
            await db.commit()

    await message.answer(f"✅ <b>Создан:</b> <code>{code}</code>\n💰 <b>{amount:,} VIRTEX</b>".replace(",", " "),
                         parse_mode="HTML")


# --- ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---
@router.message(F.text.lower().startswith("промо #"))
async def activate_promo(message: Message):
    print(f"Попытка активации промо от {message.from_user.id}")

    parts = message.text.lower().split()
    if len(parts) < 2:
        return
    code = parts[1]

    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL;")

            async with db.execute("SELECT amount, max_uses, current_uses FROM promos WHERE code = ?", (code,)) as cur:
                promo = await cur.fetchone()

            if not promo:
                return await message.reply("❌ Код не найден!")

            amount, max_uses, current_uses = promo
            if current_uses >= max_uses:
                return await message.reply("❌ Активации закончились!")

            async with db.execute("SELECT id FROM promo_logs WHERE user_id = ? AND promo_code = ?",
                                  (message.from_user.id, code)) as cur:
                if await cur.fetchone():
                    return await message.reply("❌ Вы уже активировали его!")

            # АКТИВАЦИЯ — все три операции в одной транзакции
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, f"@{message.from_user.id}")
            )
            await db.execute(
                "UPDATE promos SET current_uses = current_uses + 1 WHERE code = ?",
                (code,)
            )
            await db.execute(
                "INSERT INTO promo_logs (user_id, promo_code) VALUES (?, ?)",
                (message.from_user.id, code)
            )
            await db.commit()

    await message.reply(f"✅ Активировано! +<b>{amount:,} VIRTEX</b>".replace(",", " "), parse_mode="HTML")
