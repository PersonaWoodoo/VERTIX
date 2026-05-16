import aiosqlite
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database import DB_PATH

router = Router()

BOT_IDS = []  # добавь сюда user_id ботов если нужно исключить


@router.message(Command("top"))
async def cmd_top(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, name, balance
            FROM users
            WHERE balance > 0
              AND is_bot IS NOT 1
            ORDER BY balance DESC
            LIMIT 10
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.reply("Список богачей пока пуст!")

    lines = []
    rank = 0
    for user_id, name, balance in rows:
        if user_id in BOT_IDS:
            continue
        rank += 1
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        safe_name = name.replace("<", "&lt;").replace(">", "&gt;") if name else "Игрок"
        fmt_balance = f"{balance:,}".replace(",", " ")
        lines.append(f"{medal} {safe_name} — {fmt_balance} VIRTEX")

    if not lines:
        return await message.reply("Список богачей пока пуст!")

    response_text = "🏆 ТОП-10 БОГАТЕЙШИХ ИГРОКОВ\n\n" + "\n".join(lines)
    await message.answer(response_text, parse_mode=None)


@router.message(Command("topchat"))
async def cmd_topchat(message: Message):
    chat_id = message.chat.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем список user_id участников чата (из invited_users или user_stats)
        # Используем user_stats для определения кто пишет в чате
        async with db.execute("""
            SELECT DISTINCT s.user_id, u.name, u.balance
            FROM user_stats s
            LEFT JOIN users u ON s.user_id = CAST(SUBSTR(u.user_id, 2) AS INTEGER)
            WHERE s.chat_id = ?
              AND u.balance > 0
              AND u.is_bot IS NOT 1
            ORDER BY u.balance DESC
            LIMIT 10
        """, (chat_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.reply("В этом чате пока нет богачей!")

    lines = []
    rank = 0
    for user_id, name, balance in rows:
        if user_id in BOT_IDS:
            continue
        rank += 1
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        safe_name = name.replace("<", "&lt;").replace(">", "&gt;") if name else "Игрок"
        fmt_balance = f"{balance:,}".replace(",", " ")
        lines.append(f"{medal} {safe_name} — {fmt_balance} VIRTEX")

    if not lines:
        return await message.reply("В этом чате пока нет богачей!")

    chat_title = message.chat.title or "ЭТОМ ЧАТЕ"
    response_text = f"🏆 ТОП-10 В {chat_title.upper()}\n\n" + "\n".join(lines)
    await message.answer(response_text, parse_mode=None)
