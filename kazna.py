import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, RESTRICTED
from database import DB_PATH

router = Router()
ADMIN_IDS = [8293927811, 8478884644]

# Очередь для накопления
pending_batch = {}
batch_lock = asyncio.Lock()
BATCH_SIZE = 5
BATCH_WAIT = 15


async def process_batch(chat_id: int, bot: Bot):
    await asyncio.sleep(BATCH_WAIT)
    async with batch_lock:
        if chat_id not in pending_batch:
            return
        batch = pending_batch[chat_id].copy()
        del pending_batch[chat_id]
    if not batch:
        return

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        for inviter_id, count in batch.items():
            cur = await db.execute("SELECT reward_per_user FROM group_kazna WHERE chat_id = ? AND status = 1", (chat_id,))
            row = await cur.fetchone()
            if not row:
                continue
            reward = row[0]
            total = reward * count
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total, f"@{inviter_id}"))
            await db.execute("UPDATE group_kazna SET balance = balance - ? WHERE chat_id = ?", (total, chat_id))
            try:
                await bot.send_message(
                    inviter_id,
                    f"👥 Вы пригласили <b>{count}</b> чел!\n💰 Награда: <b>{total:,} VIRTEX</b>".replace(",", " "),
                    parse_mode="HTML"
                )
            except:
                pass
        await db.commit()


async def init_kazna_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_kazna (
                chat_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                reward_per_user INTEGER DEFAULT 0,
                status INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invited_users (
                chat_id INTEGER, invited_id INTEGER, inviter_id INTEGER,
                PRIMARY KEY (chat_id, invited_id)
            )
        """)
        await db.commit()


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(IS_NOT_MEMBER >> (MEMBER | RESTRICTED))))
async def on_user_added(event: ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    inviter = event.from_user
    user = event.new_chat_member.user
    if user.is_bot or inviter.id == user.id:
        return

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        cur = await db.execute("SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?", (chat_id,))
        data = await cur.fetchone()
        if not data or data[2] == 0 or data[1] <= 0 or data[0] < data[1]:
            return
        cur = await db.execute("SELECT 1 FROM invited_users WHERE chat_id = ? AND invited_id = ?", (chat_id, user.id))
        if await cur.fetchone():
            return
        await db.execute("INSERT INTO invited_users (chat_id, invited_id, inviter_id) VALUES (?, ?, ?)", (chat_id, user.id, inviter.id))
        await db.commit()

    async with batch_lock:
        if chat_id not in pending_batch:
            pending_batch[chat_id] = {}
            asyncio.create_task(process_batch(chat_id, bot))
        pending_batch[chat_id][inviter.id] = pending_batch[chat_id].get(inviter.id, 0) + 1


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "+казна")
async def enable_kazna(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Только владелец группы")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO group_kazna (chat_id, balance, reward_per_user, status) VALUES (?, 0, 0, 1) ON CONFLICT(chat_id) DO UPDATE SET status = 1", (message.chat.id,))
        await db.commit()
    await message.reply(f"✅ Казна включена!\n📊 Мин. приглашений: {BATCH_SIZE}+\n⏱ Накопление: {BATCH_WAIT} сек", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "-казна")
async def disable_kazna(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Только владелец группы")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE group_kazna SET status = 0 WHERE chat_id = ?", (message.chat.id,))
        await db.commit()
    await message.reply("⛔️ Казна выключена", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("установить"))
async def set_reward(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply("❌ Только админы")
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: установить 500", parse_mode="HTML")
    amount = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE group_kazna SET reward_per_user = ? WHERE chat_id = ?", (amount, message.chat.id))
        await db.commit()
    await message.reply(f"✅ Награда: {amount:,} VIRTEX за чел".replace(",", " "), parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("пополнить"))
async def deposit_kazna(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: пополнить 1000", parse_mode="HTML")
    amount = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{message.from_user.id}",))
        bal = await cur.fetchone()
        if not bal or bal[0] < amount:
            return await message.reply("❌ Недостаточно VIRTEX")
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, f"@{message.from_user.id}"))
        await db.execute("UPDATE group_kazna SET balance = balance + ? WHERE chat_id = ?", (amount, message.chat.id))
        await db.commit()
    await message.reply(f"💰 Пополнено: {amount:,} VIRTEX".replace(",", " "), parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "казна")
async def show_kazna(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?", (message.chat.id,))
        data = await cur.fetchone()
    if not data or data[2] == 0:
        return await message.reply("❌ Казна не активирована")
    await message.reply(f"🏦 <b>Казна</b>\n💰 Баланс: {data[0]:,} VIRTEX\n👤 Награда: {data[1]:,} VIRTEX\n📊 Мин. приглашений: {BATCH_SIZE}+".replace(",", " "), parse_mode="HTML")
