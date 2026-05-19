import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, RESTRICTED
from database import DB_PATH

router = Router()
ADMIN_IDS = [8293927811, 8478884644]

# НАСТРОЙКИ КАЗНЫ
DELAY_BEFORE_PROCESS = 3   # Секунд задержки перед обработкой каждого добавления
MAX_CONCURRENT = 2         # Максимум одновременных обработок

# Семафор для ограничения количества одновременных обработок
semaphore = asyncio.Semaphore(MAX_CONCURRENT)


async def init_kazna_tables():
    """Инициализация таблиц казны"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_kazna (
                chat_id         INTEGER PRIMARY KEY,
                balance         INTEGER DEFAULT 0,
                reward_per_user INTEGER DEFAULT 0,
                status          INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invited_users (
                chat_id    INTEGER,
                invited_id INTEGER,
                inviter_id INTEGER,
                PRIMARY KEY (chat_id, invited_id)
            )
        """)
        await db.commit()


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(IS_NOT_MEMBER >> (MEMBER | RESTRICTED))))
async def on_user_added(event: ChatMemberUpdated, bot: Bot):
    """Обработчик добавления нового участника с задержкой и ограничением"""
    
    # Ждём задержку перед обработкой (чтобы не лагать бота)
    await asyncio.sleep(DELAY_BEFORE_PROCESS)
    
    # Ограничиваем количество одновременных обработок
    async with semaphore:
        
        chat_id = event.chat.id
        inviter = event.from_user
        user = event.new_chat_member.user

        # Пропускаем ботов и самоприглашения
        if user.is_bot or inviter.id == user.id:
            return

        # Проверяем казну
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            cur = await db.execute(
                "SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?",
                (chat_id,)
            )
            data = await cur.fetchone()
            
            # Если казна выключена или нет денег
            if not data or data[2] == 0 or data[1] <= 0 or data[0] < data[1]:
                return
            
            # Проверяем дубликат приглашения
            cur = await db.execute(
                "SELECT 1 FROM invited_users WHERE chat_id = ? AND invited_id = ?",
                (chat_id, user.id)
            )
            if await cur.fetchone():
                return
            
            # Сохраняем приглашение
            await db.execute(
                "INSERT INTO invited_users (chat_id, invited_id, inviter_id) VALUES (?, ?, ?)",
                (chat_id, user.id, inviter.id)
            )
            
            # Начисляем награду сразу
            reward = data[1]
            fmt_uid = f"@{inviter.id}"
            
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (reward, fmt_uid)
            )
            await db.execute(
                "UPDATE group_kazna SET balance = balance - ? WHERE chat_id = ?",
                (reward, chat_id)
            )
            await db.commit()
        
        # Отправляем сообщение пригласившему
        try:
            await bot.send_message(
                inviter.id,
                f"👤 Пользователь присоединился по вашей ссылке!\n💰 Награда: <b>{reward:,} VIRTEX</b>".replace(",", " "),
                parse_mode="HTML"
            )
        except Exception:
            pass


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "+казна")
async def enable_kazna(message: Message):
    """Включение казны (только владелец)"""
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Эта команда доступна только владельцу группы.")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO group_kazna (chat_id, balance, reward_per_user, status)
            VALUES (?, 0, 0, 1)
            ON CONFLICT(chat_id) DO UPDATE SET status = 1
        """, (message.chat.id,))
        await db.commit()
    
    await message.reply(
        "✅ <b>Казна в этой группе включена!</b>\n"
        f"⏱ Задержка обработки: <b>{DELAY_BEFORE_PROCESS} секунд</b>\n"
        f"🔄 Одновременных обработок: <b>{MAX_CONCURRENT}</b>\n\n"
        "📌 <b>Доступные команды:</b>\n"
        "• <code>установить [сумма]</code> — установить награду за человека\n"
        "• <code>пополнить [сумма]</code> — пополнить казну\n"
        "• <code>казна</code> — просмотр состояния\n"
        "• <code>-казна</code> — выключить казну",
        parse_mode="HTML"
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "-казна")
async def disable_kazna(message: Message):
    """Выключение казны (только владелец)"""
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return await message.reply("❌ Эта команда доступна только владельцу группы.")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE group_kazna SET status = 0 WHERE chat_id = ?", (message.chat.id,))
        await db.commit()
    
    await message.reply("⛔️ <b>Казна в этой группе выключена!</b>", parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("установить"))
async def set_reward(message: Message):
    """Установка награды за приглашение (только админы)"""
    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return await message.reply("❌ Только администраторы могут менять настройки.")
    
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: <code>установить 500</code>", parse_mode="HTML")
    
    amount = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE group_kazna SET reward_per_user = ? WHERE chat_id = ?",
            (amount, message.chat.id)
        )
        await db.commit()
    
    await message.reply(
        f"✅ Награда за 1 человека установлена: <b>{amount:,} VIRTEX</b>".replace(",", " "),
        parse_mode="HTML"
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("пополнить"))
async def deposit_kazna(message: Message):
    """Пополнение казны из личного баланса"""
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: <code>пополнить 1000</code>", parse_mode="HTML")
    
    amount = int(parts[1])
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id = ?", (f"@{user_id}",))
        bal = await cur.fetchone()
        if not bal or bal[0] < amount:
            return await message.reply("❌ Недостаточно VIRTEX на балансе!")
        
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, f"@{user_id}"))
        await db.execute(
            "UPDATE group_kazna SET balance = balance + ? WHERE chat_id = ?",
            (amount, message.chat.id)
        )
        await db.commit()
    
    await message.reply(
        f"💰 Вы пополнили казну на <b>{amount:,} VIRTEX</b>!".replace(",", " "),
        parse_mode="HTML"
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "казна")
async def show_kazna(message: Message):
    """Просмотр состояния казны"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?",
            (message.chat.id,)
        )
        data = await cur.fetchone()
    
    if not data or data[2] == 0:
        return await message.reply("❌ Казна в этой группе не активирована.")
    
    balance, reward, status = data
    
    # Получаем количество приглашённых пользователей
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM invited_users WHERE chat_id = ?",
            (message.chat.id,)
        )
        invited_count = (await cur.fetchone())[0]
    
    await message.reply(
        f"🏦 <b>Казна группы</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс казны: <b>{balance:,} VIRTEX</b>\n"
        f"👤 Награда за 1 чел: <b>{reward:,} VIRTEX</b>\n"
        f"📊 Приглашено всего: <b>{invited_count}</b> чел.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ <b>Настройки нагрузки:</b>\n"
        f"⏱ Задержка обработки: <b>{DELAY_BEFORE_PROCESS} сек</b>\n"
        f"🔄 Максимум одновременных: <b>{MAX_CONCURRENT}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Команды:</b>\n"
        f"• <code>установить [сумма]</code> — изменить награду\n"
        f"• <code>пополнить [сумма]</code> — пополнить казну\n"
        f"• <code>-казна</code> — выключить казну".replace(",", " "),
        parse_mode="HTML"
    )
