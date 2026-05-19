import os
import asyncio
import aiosqlite

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import TelegramObject, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database
from cmd_b import router as balance_router
from transf import router as transfer_router
from donate import router as donate_router
from bonus import router as bonus_router
from start import router as start_router
from mines import router as mines_router
import ctra
import setns
import help
import top
import kazna
import kalculator
from tur import router as tur_router, init_tournament_db, daily_tournament_reset
from adm import router as admin_router
from promo import router as promo_router
from roulette import router as roulette_router
from gold import router as gold_router
from ref import router as ref_router, init_ref_tables
from kazna import init_kazna_tables

db_dir = os.path.dirname(os.getenv("DB_PATH", "bot_db.sqlite"))
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir)

BOT_TOKEN = "8657372135:AAEF-epUaZBTh2k3tjlck4X3KLrBMxELC-Q"


class RegistrationAndBanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, Message):
            return await handler(event, data)

        message = event
        user = message.from_user

        if user:
            if database.is_user_banned(user.id):
                return None
            database.add_user(user.id, user.first_name, user.username)
            database.update_user_info(user.id, user.first_name, user.username)

        if message.chat.type in ["group", "supergroup"] and message.text:
            text = message.text.lower()
            chat_id = message.chat.id
            game_col = None

            if text.startswith("рулетка"):
                game_col = "roulette_status"
            elif text.startswith("мины"):
                game_col = "mines_status"
            elif text.startswith("краш"):
                game_col = "crash_status"

            if game_col:
                async with aiosqlite.connect(database.DB_PATH, timeout=20) as db:
                    async with db.execute(
                        f"SELECT {game_col} FROM group_settings WHERE chat_id = ?",
                        (chat_id,)
                    ) as cur:
                        row = await cur.fetchone()
                        if row and row[0] == 0:
                            try:
                                return await message.reply("🚫 <b>Игра отключена администратором!</b>", parse_mode="HTML")
                            except Exception:
                                return None

        try:
            return await handler(event, data)
        except TelegramRetryAfter as e:
            print(f"Флуд-контроль! Ждем {e.retry_after} сек.")
            await asyncio.sleep(e.retry_after)
            return await handler(event, data)


async def main():
    print("Инициализация базы данных...")
    database.init_db()
    init_ref_tables()
    await init_kazna_tables()
    await init_tournament_db()
    print("База данных готова")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.outer_middleware(RegistrationAndBanMiddleware())

    dp.include_routers(
        admin_router,
        kazna.router,
        balance_router,
        transfer_router,
        bonus_router,
        donate_router,
        start_router,
        roulette_router,
        mines_router,
        gold_router,
        ref_router,
        ctra.router,
        promo_router,
        setns.router,
        help.router,
        top.router,
        tur_router,
        kalculator.router,
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        daily_tournament_reset,
        trigger=CronTrigger(hour=0, minute=0, timezone="Europe/Moscow"),
        args=[bot]
    )
    scheduler.start()
    print("[ТУРНИР] Планировщик запущен (сброс в 00:00 МСК)")

    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Система остановлена")
