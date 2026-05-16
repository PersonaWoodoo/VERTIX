import asyncio
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()
DB_PATH = "bot_db.sqlite"

ADMIN_IDS = [8293927811, 8478884644]

rewards = {1: 300000, 2: 150000, 3: 100000, 4: 50000, 5: 25000}

# Глобальный лок для защиты от "database is locked"
db_lock = asyncio.Lock()


# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_tournament_db():
    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournament_stats (
                    user_id INTEGER PRIMARY KEY,
                    user_name TEXT,
                    profit INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournament_history (
                    place     INTEGER,
                    user_id   INTEGER,
                    user_name TEXT,
                    profit    INTEGER
                )
            """)
            try:
                await db.execute("ALTER TABLE tournament_history ADD COLUMN user_id INTEGER")
            except Exception:
                pass
            await db.commit()


# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: начислить одному победителю ---
async def _give_reward(db: aiosqlite.Connection, bot: Bot, place: int, uid: int, name: str, profit: int) -> tuple:
    reward = rewards.get(place)
    if not reward:
        return "", False

    fmt_uid = f"@{uid}"

    async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (fmt_uid,)) as cur:
        existing = await cur.fetchone()

    if not existing:
        return f"{place}. {name} (id={uid}) — ❌ не найден в users", False

    await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, fmt_uid))
    await db.commit()

    fmt_reward = f"{reward:,}".replace(",", " ")
    fmt_profit = f"{profit:,}".replace(",", " ")

    notified = True
    try:
        await bot.send_message(
            int(uid),
            f"<b>🏆 Награда за турнир!</b>\n\n"
            f"Вы заняли <b>{place} место</b> с прибылью <b>{fmt_profit} VIRTEX</b>.\n"
            f"Начислено: <b>{fmt_reward} VIRTEX</b>",
            parse_mode="HTML"
        )
    except Exception:
        notified = False

    line = f"{place}. {name} — +{fmt_reward} VIRTEX ✅"
    if not notified:
        line += " (уведомление не доставлено)"
    return line, True


# --- АВТОСБРОС В 00:00 ПО МСК ---
async def daily_tournament_reset(bot: Bot):
    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id, user_name, profit FROM tournament_stats ORDER BY profit DESC LIMIT 10"
            ) as cur:
                winners = await cur.fetchall()

            if not winners:
                return

            await db.execute("DELETE FROM tournament_history")
            for i, (uid, name, profit) in enumerate(winners, 1):
                await db.execute(
                    "INSERT INTO tournament_history (place, user_id, user_name, profit) VALUES (?, ?, ?, ?)",
                    (i, uid, name, profit)
                )
            await db.commit()

            for i, (uid, name, profit) in enumerate(winners, 1):
                await _give_reward(db, bot, i, uid, name, profit)

            await db.execute("DELETE FROM tournament_stats")
            await db.commit()

    print("[ТУРНИР] Сброс выполнен, награды выданы.")


# --- КОМАНДА /начислить ---
@router.message(F.text.startswith("/начислить"))
async def cmd_manual_reward(message: Message, bot: Bot):
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return await message.reply("🚫 У вас нет прав для этой команды.")

    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT place, user_id, user_name, profit FROM tournament_history ORDER BY place ASC"
            ) as cur:
                history = await cur.fetchall()

            if not history:
                return await message.reply("❌ История предыдущего турнира пуста.")

            report_lines = []
            problem_lines = []

            for row in history:
                place, uid, name, profit = row

                if uid is None:
                    problem_lines.append(f"{place}. {name} — ⚠️ user_id не сохранён")
                    continue

                line, ok = await _give_reward(db, bot, place, uid, name, profit)
                if line:
                    if ok:
                        report_lines.append(line)
                    else:
                        problem_lines.append(line)

    text = "<b>✅ Начисление завершено:</b>\n\n"
    text += "\n".join(report_lines) if report_lines else "Никому не начислено."
    if problem_lines:
        text += "\n\n<b>⚠️ Проблемы:</b>\n" + "\n".join(problem_lines)

    await message.reply(text, parse_mode="HTML")


# --- ХЕНДЛЕРЫ ---
@router.message(F.text == "🏆 Турниры")
async def show_tournament(message: Message):
    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_name, profit FROM tournament_stats ORDER BY profit DESC LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()

    text = "<b>🏆 Текущий турнир рулетки</b>\n\n"
    if not rows:
        text += "Турнир только начался, ставок еще нет!"
    else:
        for i, (name, profit) in enumerate(rows, 1):
            fmt_profit = f"{profit:,}".replace(",", " ")
            text += f"{i}. {name} — <b>{fmt_profit} VIRTEX</b>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Формат турнира", callback_data="tur_format")],
        [InlineKeyboardButton(text="⏳ Предыдущий турнир", callback_data="tur_prev")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "tur_format")
async def info_format(call: CallbackQuery):
    await call.answer()
    text = (
        "🏆 <b>ТУРНИР: VIRTEX ROULETTE</b>\n"
        "──────────────────────────\n\n"
        "Ежедневный турнир с автоматическим участием.\n"
        "Обновление таблицы лидеров происходит в <b>00:00 по МСК</b>.\n\n"
        "<b>ПРАВИЛА И ПОДСЧЕТ ОЧКОВ</b>\n"
        "Рейтинг строится на основе чистой прибыли (Выигрыш − Ставка).\n"
        "Проигрышные ставки не уменьшают ваш текущий результат.\n\n"
        "<b>Пример расчета:</b>\n"
        "▫️ Ставка 1,000 | Выигрыш 1,200 — в таблицу идет <code>+200</code>\n"
        "▫️ Ставка 1,000 | Проигрыш — результат не меняется\n\n"
        "──────────────────────────\n"
        "<b>НАГРАДЫ ДЛЯ ТОП-5</b>\n\n"
        "1. 🥇 <code>300,000 VIRTEX</code>\n"
        "2. 🥈 <code>150,000 VIRTEX</code>\n"
        "3. 🥉 <code>100,000 VIRTEX</code>\n"
        "4. 🎖 <code>50,000 VIRTEX</code>\n"
        "5. 🎖 <code>25,000 VIRTEX</code>\n\n"
        "──────────────────────────\n"
        "<i>Результаты обновляются автоматически.</i>"
    )
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="tur_back")]
        ])
    )


@router.callback_query(F.data == "tur_prev")
async def info_prev(call: CallbackQuery):
    await call.answer()
    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT place, user_name, profit FROM tournament_history ORDER BY place ASC"
            ) as cur:
                rows = await cur.fetchall()

    text = "<b>⏳ Результаты последнего турнира:</b>\n\n"
    if not rows:
        text += "Данных еще нет."
    else:
        for place, name, profit in rows:
            fmt_profit = f"{profit:,}".replace(",", " ")
            text += f"{place}. {name} — <b>{fmt_profit} VIRTEX</b>\n"

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="tur_back")]
        ])
    )


@router.callback_query(F.data == "tur_back")
async def back_to_tur(call: CallbackQuery):
    await call.answer()
    async with db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_name, profit FROM tournament_stats ORDER BY profit DESC LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()

    text = "<b>🏆 Текущий турнир рулетки</b>\n\n"
    if not rows:
        text += "Турнир только начался!"
    else:
        for i, (name, profit) in enumerate(rows, 1):
            text += f"{i}. {name} — <b>{f'{profit:,}'.replace(',', ' ')} VIRTEX</b>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Формат турнира", callback_data="tur_format")],
        [InlineKeyboardButton(text="⏳ Предыдущий турнир", callback_data="tur_prev")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
