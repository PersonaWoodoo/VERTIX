import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, RESTRICTED
from database import DB_PATH

router = Router()
# Список ID пользователей, которым разрешено использовать админ-команды
ADMIN_IDS = [8293927811, 8478884644]


# ────────────────────────────────────────────────────────────────────────────
#  Один глобальный семафор — не более 3 одновременных операций с БД
#  Это решает "database is locked" при массовом входе пользователей
# ────────────────────────────────────────────────────────────────────────────
_db_sem = asyncio.Semaphore(3)


async def _execute(sql: str, params: tuple = (), *, fetchone=False, fetchall=False, commit=False):
    """
    Универсальная обёртка для работы с БД.
    — WAL-режим включён один раз на соединение
    — Автоматический retry при SQLITE_BUSY (до 5 попыток)
    — Семафор ограничивает параллельность
    """
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
                print(f"[kazna] БД занята, попытка {attempt + 1}/{retries}, жду {wait:.1f}с...")
                await asyncio.sleep(wait)
                continue
            raise  # другие ошибки — пробрасываем сразу

    raise RuntimeError(f"[kazna] БД заблокирована после {retries} попыток: {sql[:60]}")


async def _execute_many(statements: list[tuple], *, commit=True):
    """
    Несколько операций в одной транзакции — атомарно и быстро.
    statements = [(sql, params), ...]
    """
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
                print(f"[kazna] БД занята (many), попытка {attempt + 1}/{retries}, жду {wait:.1f}с...")
                await asyncio.sleep(wait)
                continue
            raise

    raise RuntimeError(f"[kazna] БД заблокирована (many) после {retries} попыток")


# ────────────────────────────────────────────────────────────────────────────
#  Инициализация таблиц (вызывается один раз при старте)
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
                PRIMARY KEY (chat_id, invited_id)
            )''', ()),
        ('''CREATE TABLE IF NOT EXISTS mine_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )''', ()),
    ])

# ────────────────────────────────────────────────────────────────────────────
#  Вспомогательные функции
# ────────────────────────────────────────────────────────────────────────────
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


async def get_kazna_settings():
    """Получает кастомные эмодзи для казны из БД — через общую обёртку с WAL и семафором."""
    rows = await _execute(
        "SELECT key, value FROM mine_settings WHERE key IN ('kazna_emoji', 'kazna_reward_emoji')",
        fetchall=True,
    )
    settings = {row[0]: row[1] for row in rows} if rows else {}
    return (
        settings.get('kazna_emoji', '🏦'),
        settings.get('kazna_reward_emoji', '👤')
    )


# ────────────────────────────────────────────────────────────────────────────
#  1. Включение казны (только владелец группы)
# ────────────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────────────
#  1.5 Выключение казны (только владелец группы)
# ────────────────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────────────────
#  2. Установка суммы награды
# ────────────────────────────────────────────────────────────────────────────
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
    await message.reply(
        f"✅ Награда за 1 человека установлена: <b>{fmt_amount} VIRTEX</b>",
        parse_mode="HTML",
    )


# ────────────────────────────────────────────────────────────────────────────
#  3. Пополнение казны
# ────────────────────────────────────────────────────────────────────────────
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower().startswith("пополнить"))
async def deposit_kazna(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply("Использование: <code>пополнить 1000</code>", parse_mode="HTML")

    amount   = int(parts[1])
    user_id  = message.from_user.id
    uid      = f"@{user_id}"

    bal = await get_user_balance(user_id)
    if bal < amount:
        return await message.reply("❌ У вас недостаточно VIRTEX для пополнения казны.")

    await _execute_many([
        ("UPDATE users SET balance = balance - ? WHERE user_id = ?",        (amount, uid)),
        ("UPDATE group_kazna SET balance = balance + ? WHERE chat_id = ?",  (amount, message.chat.id)),
    ])

    fmt_amount = f"{amount:,}".replace(",", " ")
    await message.reply(
        f"💰 Вы пополнили казну на <b>{fmt_amount} VIRTEX</b>!",
        parse_mode="HTML",
    )


# ────────────────────────────────────────────────────────────────────────────
#  4. Просмотр состояния казны
# ────────────────────────────────────────────────────────────────────────────
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.lower() == "казна")
async def show_kazna(message: Message):
    data = await get_kazna_data(message.chat.id)
    if not data or data[2] == 0:
        return await message.reply("❌ Казна в этой группе не активирована.")

    balance, reward, status = data
    k_emoji, r_emoji = await get_kazna_settings()

    fmt_balance = f"{balance:,}".replace(",", " ")
    fmt_reward = f"{reward:,}".replace(",", " ")

    text = (
        f"{k_emoji} <b>казна группы</b>\n"
        f"💰Баланс : <b>{fmt_balance} VIRTEX</b>\n"
        f"{r_emoji} Награда: <b>{fmt_reward} за чел.</b>"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(F.text.lower().startswith("/kkaznnna"))
async def cmd_set_kazna_style(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.reply("❌ У вас нет прав для использования этой команды.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply(
            "Использование:\n"
            "<code>/kkaznnna [эмодзи]</code> — сменить эмодзи казны\n"
            "<code>/kkaznnna [эмодзи] [награда]</code> — сменить эмодзи награды и сумму",
            parse_mode="HTML"
        )

    new_emoji = parts[1]

    if message.entities:
        for ent in message.entities:
            if ent.type == "custom_emoji":
                placeholder = ent.extract_from(message.text)
                new_emoji = f'<tg-emoji emoji-id="{ent.custom_emoji_id}">{placeholder}</tg-emoji>'
                break
            elif ent.type == "emoji":
                new_emoji = ent.extract_from(message.text)
                break

    if len(parts) >= 3 and parts[2].isdigit():
        new_reward = int(parts[2])
        await _execute_many([
            (
                "INSERT INTO mine_settings (key, value) VALUES ('kazna_reward_emoji', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (new_emoji,),
            ),
            (
                "UPDATE group_kazna SET reward_per_user = ? WHERE chat_id = ?",
                (new_reward, message.chat.id),
            ),
        ])
        await message.reply(f"✅ Награда обновлена: {new_emoji} {new_reward} VIRTEX", parse_mode="HTML")
    else:
        await _execute(
            "INSERT INTO mine_settings (key, value) VALUES ('kazna_emoji', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (new_emoji,),
            commit=True,
        )
        await message.reply(f"✅ Эмодзи казны обновлен на: {new_emoji}", parse_mode="HTML")


# ────────────────────────────────────────────────────────────────────────────
#  5. Логика начисления при добавлении пользователя
# ────────────────────────────────────────────────────────────────────────────
@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(IS_NOT_MEMBER >> (MEMBER | RESTRICTED))))
async def on_user_added(event: ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    inviter = event.from_user
    user    = event.new_chat_member.user

    # Скипаем ботов
    if user.is_bot:
        return

    # Зашёл сам по ссылке — не начисляем
    if inviter.id == user.id:
        return

    fmt_inviter_id = f"@{inviter.id}"

    # ── EXCLUSIVE транзакция: только один поток за раз обрабатывает начисление ──
    # Это решает race condition при массовом добавлении (10 событий одновременно)
    retries = 5
    for attempt in range(retries):
        try:
            async with _db_sem:
                async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL;")
                    await db.execute("PRAGMA synchronous=NORMAL;")
                    await db.execute("PRAGMA busy_timeout=10000;")

                    # BEGIN EXCLUSIVE — никто другой не читает/пишет пока мы внутри
                    await db.execute("BEGIN EXCLUSIVE")

                    try:
                        # 1. Проверяем казну (читаем ВНУТРИ эксклюзивной блокировки)
                        cur = await db.execute(
                            "SELECT balance, reward_per_user, status FROM group_kazna WHERE chat_id = ?",
                            (chat_id,),
                        )
                        data = await cur.fetchone()

                        if not data:
                            await db.execute("ROLLBACK")
                            return

                        balance, reward, status = data
                        if status == 0 or reward <= 0:
                            await db.execute("ROLLBACK")
                            return

                        if balance < reward:
                            print(f"[kazna] Кончились деньги в казне чата {chat_id}. Остаток: {balance}, нужно: {reward}")
                            await db.execute("ROLLBACK")
                            return

                        # 2. Проверяем дубликат (тоже внутри блокировки — нет race condition)
                        cur = await db.execute(
                            "SELECT 1 FROM invited_users WHERE chat_id = ? AND invited_id = ?",
                            (chat_id, user.id),
                        )
                        already = await cur.fetchone()
                        if already:
                            await db.execute("ROLLBACK")
                            return

                        # 3. Всё чисто — записываем атомарно
                        await db.execute(
                            "INSERT OR IGNORE INTO invited_users (chat_id, invited_id) VALUES (?, ?)",
                            (chat_id, user.id),
                        )
                        await db.execute(
                            "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                            (fmt_inviter_id,),
                        )
                        await db.execute(
                            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                            (reward, fmt_inviter_id),
                        )
                        await db.execute(
                            "UPDATE group_kazna SET balance = balance - ? WHERE chat_id = ?",
                            (reward, chat_id),
                        )
                        await db.execute("COMMIT")

                    except Exception:
                        await db.execute("ROLLBACK")
                        raise

            # ── Выходим из цикла retry если всё ок ──
            break

        except Exception as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                wait = 0.2 * (attempt + 1)
                print(f"[kazna] БД занята (on_user_added), попытка {attempt + 1}/{retries}, жду {wait:.1f}с...")
                await asyncio.sleep(wait)
                continue
            print(f"[kazna] Ошибка при начислении награды: {e}")
            return

    else:
        print(f"[kazna] БД заблокирована (on_user_added) после {retries} попыток, чат {chat_id}")
        return

    # ── Отправляем сообщение о награде (вне блока БД) ──
    safe_user_name    = user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    safe_inviter_name = inviter.first_name.replace('<', '&lt;').replace('>', '&gt;')
    invited_mention   = f'<a href="tg://user?id={user.id}">{safe_user_name}</a>'
    inviter_mention   = f'<a href="tg://user?id={inviter.id}">{safe_inviter_name}</a>'
    fmt_pay           = f"{reward:,}".replace(",", " ")

    text = (
        f"👤 {inviter_mention} добавил {invited_mention}\n"
        f"💰 Награда из казны: <b>{fmt_pay} VIRTEX</b>"
    )

    for attempt in range(3):
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
            else:
                print(f"[kazna] Не удалось отправить сообщение в чат {chat_id}: {e}")
