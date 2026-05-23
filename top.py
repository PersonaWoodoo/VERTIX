import aiosqlite
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database import DB_PATH

router = Router()


@router.message(Command("top"))
async def cmd_top(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, name, balance
            FROM users
            WHERE balance > 0 AND is_bot IS NOT 1
            ORDER BY balance DESC LIMIT 10
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.reply("📭 Список богачей пуст")

    lines = ["🏆 <b>ТОП-10 БОГАТЕЙШИХ</b>\n"]
    for i, (user_id, name, balance) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        safe_name = name.replace("<", "&lt;").replace(">", "&gt;") if name else "Игрок"
        lines.append(f"{medal} {safe_name} — {balance:,} VIRTEX".replace(",", " "))
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("topchat"))
async def cmd_topchat(message: Message):
    chat_id = message.chat.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT DISTINCT s.user_id, u.name, u.balance
            FROM user_stats s
            LEFT JOIN users u ON s.user_id = CAST(SUBSTR(u.user_id, 2) AS INTEGER)
            WHERE s.chat_id = ? AND u.balance > 0 AND u.is_bot IS NOT 1
            ORDER BY u.balance DESC LIMIT 10
        """, (chat_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.reply("📭 В этом чате пока нет богачей")

    lines = [f"🏆 <b>ТОП-10 В ЧАТЕ</b>\n"]
    for i, (user_id, name, balance) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        safe_name = name.replace("<", "&lt;").replace(">", "&gt;") if name else "Игрок"
        lines.append(f"{medal} {safe_name} — {balance:,} VIRTEX".replace(",", " "))
    await message.answer("\n".join(lines), parse_mode="HTML")
