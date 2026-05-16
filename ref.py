import sqlite3
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart

import database

router = Router()

BOT_USERNAME = "virrtexbot"
REF_REWARD = 2500
CURRENCY_NAME = "VIRTEX"

CUSTOM_EMOJI_NAME     = "<tg-emoji emoji-id='5326037211164978005'>👤</tg-emoji>"
CUSTOM_EMOJI_INVITED  = "<tg-emoji emoji-id='5215720576735255650'>👥</tg-emoji>"
CUSTOM_EMOJI_JOIN     = "<tg-emoji emoji-id='5388632425314140043'>🎉</tg-emoji>"


# ───────────────────────────── DB helpers ──────────────────────────────

def init_ref_tables():
    with sqlite3.connect(database.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                invitee_id INTEGER PRIMARY KEY,
                inviter_id INTEGER NOT NULL,
                date_time  TEXT    NOT NULL
            )
        ''')
        conn.commit()


def get_inviter(invitee_id: int):
    with sqlite3.connect(database.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT inviter_id FROM referrals WHERE invitee_id = ?", (invitee_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def save_referral(invitee_id: int, inviter_id: int) -> int:
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(database.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO referrals (invitee_id, inviter_id, date_time) VALUES (?, ?, ?)",
            (invitee_id, inviter_id, now)
        )
        conn.commit()
        return cursor.rowcount


def count_referrals(inviter_id: int) -> int:
    with sqlite3.connect(database.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (inviter_id,))
        return cursor.fetchone()[0]


def get_user_mention(user_id: int, full_name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{full_name}</a>'


# ───────────────────────────── Handlers ────────────────────────────────

@router.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: Message):
    args = message.text.split(maxsplit=1)
    payload = args[1] if len(args) > 1 else ""

    if not payload.startswith("ref_"):
        return

    inviter_id_str = payload[4:]
    if not inviter_id_str.isdigit():
        return

    inviter_id = int(inviter_id_str)
    invitee_id = message.from_user.id

    if inviter_id == invitee_id:
        return

    written = save_referral(invitee_id, inviter_id)

    if written:
        # Начисляем баланс через синхронную функцию database
        fmt_id = f"@{inviter_id}"
        with sqlite3.connect(database.DB_PATH) as conn:
            conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (REF_REWARD, fmt_id)
            )
            conn.commit()

        invitee_mention = get_user_mention(invitee_id, message.from_user.full_name)

        try:
            await message.bot.send_message(
                chat_id=inviter_id,
                text=(
                    f"{CUSTOM_EMOJI_JOIN} {invitee_mention} вступил по реферальной ссылке\n"
                    f"Начислено вам <b>{REF_REWARD:,}</b> {CURRENCY_NAME}".replace(",", "\u202f")
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass


@router.message(
    F.chat.type == "private",
    F.text.lower().in_({"👤реферал", "реферал", "👤 реферал"})
)
async def cmd_ref(message: Message):
    user = message.from_user
    user_id = user.id
    mention = get_user_mention(user_id, user.full_name)

    invited_count = count_referrals(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

    text = (
        f"{CUSTOM_EMOJI_NAME} {mention}\n"
        f"{CUSTOM_EMOJI_INVITED} Приглашённых: <b>{invited_count}</b>\n\n"
        f"🔗 Ваша реферальная ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"За каждого приглашённого: <b>+{REF_REWARD:,}</b> {CURRENCY_NAME}".replace(",", "\u202f")
    )

    await message.answer(text, parse_mode="HTML")
