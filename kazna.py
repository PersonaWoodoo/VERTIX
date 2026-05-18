import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, RESTRICTED
from database import DB_PATH

router = Router()
ADMIN_IDS = [8293927811, 8478884644]

_db_sem = asyncio.Semaphore(3)


async def _execute(sql: str, params: tuple = (), *, fetchone=False, fetchall=False, commit=False):
    retries = 5
    for attempt in range(retries):
        try:
            async with _db_sem:
                async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL;")
                    await db.execute("PRAGMA synchronous=NORMAL;")
                    await db.execute("PRAGMA busy_timeout=10000;")
                    cur = await db.execute(sql, params)
                    result = None
                    if fetchone:
                        result = await cur.fetchone()
                    elif fetchall:
                        result = await cur.fetchall()
                    if commit:
                        await db.commit()
                    return result
        except Exception as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                wait = 0.2 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise
    raise RuntimeError(f"БД заблокирована: {sql[:60]}")


async def _execute_many(statements: list[tuple], *, commit=True):
    retries = 5
    for attempt in range(retries):
        try:
            async with _db_sem:
                async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL;")
                    await db.execute("PRAGMA synchronous=NORMAL;")
                    await db.execute("PRAGMA busy_timeout=10000;")
                    for sql, params in statements:
                        await db.execute(sql, params)
                    if commit:
                        await db.commit()
            return
        except Exception as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                wait = 0.2 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise
    raise RuntimeError("БД заблокирована (many)")


async def init_kazna_tables():
    await _execute_many([
        ('''CREATE TABLE IF NOT EXISTS group_kazna (
                chat_id         INTEGER PRIMARY KEY,
                balance         INTEGER DEFAULT 0,
                reward_per_user INTEGER DEFAULT 0,
                status          INTEGER DEFAULT 0
            )''', ()),
        ('''CREATE TABLE IF NOT EXISTS invited_users (
                chat_id    INTEGER,
                invited_id INTEGER,
                inviter_id INTEGER,
                PRIMARY KEY (chat_id, invited_id)
            )''', ()),
        ('''CREATE TABLE IF NOT EXISTS mine_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )''', ()),
    ])


async def get_kazna_data(chat_id: int):
    return await _execute(
        "SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?",
        (chat_id,),
        fetchone=True,
    )


async def get_user_balance(user_id: int) -> int:
    uid = f"@{user_id}"
    row = await _execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (uid,),
        fetchone=True,
    )
    return row[0] if row else 0


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "+казна")
async def enable_kazna(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Эта команда доступна только владельцу группы.")
    await _execute(
        '''INSERT INTO group_kazna (chat_id, balance, reward_per_user, status)
           VALUES (?, 0, 0, 1)
           ON CONFLICT(chat_id) DO UPDATE SET status = 1''',
        (message.chat.id,),
        commit=True,
    )
    await message.reply("✅ <b>Казна в этой группе включена!</b>", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "-казна")
async def disable_kazna(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Эта команда доступна только владельцу группы.")
    await _execute(
        "UPDATE group_kazna SET status = 0 WHERE chat_id = ?",
        (message.chat.id,),
        commit=True,
    )
    await message.reply("⛔️ <b>Казна в этой группе выключена!</b>", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("установить"))
async def set_reward(message: Message):
    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply("❌ Только админы могут менять настройки.")
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: <code>установить 500</code>", parse_mode="HTML")
    amount = int(parts[1])
    await _execute(
        "UPDATE group_kazna SET reward_per_user = ? WHERE chat_id = ?",
        (amount, message.chat.id),
        commit=True,
    )
    fmt_amount = f"{amount:,}".replace(",", " ")
    await message.reply(f"✅ Награда за 1 человека установлена: <b>{fmt_amount} VIRTEX</b>", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("пополнить"))
async def deposit_kazna(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: <code>пополнить 1000</code>", parse_mode="HTML")
    amount = int(parts[1])
    user_id = message.from_user.id
    uid = f"@{user_id}"
    bal = await get_user_balance(user_id)
    if bal < amount:
        return await message.reply("❌ У вас недостаточно VIRTEX для пополнения казны.")
    await _execute_many([
        ("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, uid)),
        ("UPDATE group_kazna SET balance = balance + ? WHERE chat_id = ?", (amount, message.chat.id)),
    ])
    fmt_amount = f"{amount:,}".replace(",", " ")
    await message.reply(f"💰 Вы пополнили казну на <b>{fmt_amount} VIRTEX</b>!", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "казна")
async def show_kazna(message: Message):
    data = await get_kazna_data(message.chat.id)
    if not data or data[2] == 0:
        return await message.reply("❌ Казна в этой группе не активирована.")
    balance, reward, status = data
    fmt_balance = f"{balance:,}".replace(",", " ")
    fmt_reward = f"{reward:,}".replace(",", " ")
    text = f"🏦 <b>Казна группы</b>\n💰 Баланс: <b>{fmt_balance} VIRTEX</b>\n👤 Награда: <b>{fmt_reward} за чел.</b>"
    await message.reply(text, parse_mode="HTML")


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(IS_NOT_MEMBER >> (MEMBER | RESTRICTED))))
async def on_user_added(event: ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    inviter = event.from_user
    user = event.new_chat_member.user

    if user.is_bot:
        return
    if inviter.id == user.id:
        return

    data = await get_kazna_data(chat_id)
    if not data or data[2] == 0:
        return
    balance, reward, status = data
    if status == 0 or reward <= 0:
        return
    if balance < reward:
        return

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("BEGIN EXCLUSIVE")
        try:
            cur = await db.execute(
                "SELECT 1 FROM invited_users WHERE chat_id = ? AND invited_id = ?",
                (chat_id, user.id)
            )
            if await cur.fetchone():
                await db.execute("ROLLBACK")
                return

            await db.execute(
                "INSERT INTO invited_users (chat_id, invited_id, inviter_id) VALUES (?, ?, ?)",
                (chat_id, user.id, inviter.id)
            )
            await db.commit()
        except Exception:
            await db.execute("ROLLBACK")
            return

    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM invited_users WHERE chat_id = ? AND inviter_id = ?",
            (chat_id, inviter.id)
        )
        invited_count = (await cur.fetchone())[0]

        total_reward = invited_count * reward
        fmt_uid = f"@{inviter.id}"
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
            (fmt_uid,)
        )
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (reward, fmt_uid)
        )
        await db.execute(
            "UPDATE group_kazna SET balance = balance - ? WHERE chat_id = ?",
            (reward, chat_id)
        )
        await db.commit()

    safe_user_name = user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    safe_inviter_name = inviter.first_name.replace('<', '&lt;').replace('>', '&gt;')
    invited_mention = f'<a href="tg://user?id={user.id}">{safe_user_name}</a>'
    inviter_mention = f'<a href="tg://user?id={inviter.id}">{safe_inviter_name}</a>'
    fmt_reward = f"{reward:,}".replace(",", " ")

    text = (
        f"👤 {inviter_mention} пригласил {invited_mention}\n"
        f"📊 Всего приглашений: <b>{invited_count}</b>\n"
        f"💰 Получено за это приглашение: <b>{fmt_reward} VIRTEX</b>"
    )
    await bot.send_message(chat_id, text, parse_mode="HTML")
