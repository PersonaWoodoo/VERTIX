import sqlite3
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import database

router = Router()
ADMIN_IDS = [8293927811, 8478884644]


class AdminStates(StatesGroup):
    wait_for_amount = State()


# ---------------------------------------------------------------------------
# Клавиатура профиля
# ---------------------------------------------------------------------------

def get_check_kb(target_id: str, is_banned: bool, has_vip: bool) -> InlineKeyboardMarkup:
    target_id = str(target_id).replace("@", "")

    ban_btn = (
        InlineKeyboardButton(text="🔓 Разбанить", callback_data=f"check_unban_{target_id}")
        if is_banned
        else InlineKeyboardButton(text="🚫 Забанить", callback_data=f"check_ban_{target_id}")
    )

    vip_btn = (
        InlineKeyboardButton(text="❌ Снять VIP", callback_data=f"check_revip_{target_id}")
        if has_vip
        else InlineKeyboardButton(text="👑 Выдать VIP", callback_data=f"check_givip_{target_id}")
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 +VIRTEX",    callback_data=f"check_add_balance_{target_id}"),
            InlineKeyboardButton(text="💸 −VIRTEX",    callback_data=f"check_rem_balance_{target_id}"),
        ],
        [
            InlineKeyboardButton(text="⭐️ +Звёзды", callback_data=f"check_add_stars_{target_id}"),
            InlineKeyboardButton(text="✂️ −Звёзды",  callback_data=f"check_rem_stars_{target_id}"),
        ],
        [vip_btn, ban_btn],
        [
            InlineKeyboardButton(text="🔄 Обновить",          callback_data=f"check_refresh_{target_id}"),
            InlineKeyboardButton(text="🗑 Обнулить ⭐️ ВСЕМ",  callback_data="check_resetallstars"),
        ],
    ])


# ---------------------------------------------------------------------------
# Текст карточки пользователя
# ---------------------------------------------------------------------------

def build_profile_text(target_id: str, name: str, balance: int, stars: int,
                        is_banned: bool, has_vip: bool) -> str:
    unit_icon  = database.get_setting("plugs_icon", "💰")
    stars_icon = database.get_setting("stars_icon", "⭐️")

    fmt_balance = f"{balance:,}".replace(",", " ")
    fmt_stars   = f"{stars:,}".replace(",", " ")
    status_line = "🔴 Заблокирован" if is_banned else "🟢 Активен"
    vip_line    = "💎 Есть" if has_vip else "❌ Нет"

    return (
        f"┌─ 👤 <b>{name}</b>\n"
        f"├─ 🆔 <code>@{target_id}</code>\n"
        f"├─ {unit_icon} VIRTEX: <b>{fmt_balance}</b>\n"
        f"├─ {stars_icon} Звёзды: <b>{fmt_stars}</b>\n"
        f"├─ 📊 Статус: {status_line}\n"
        f"└─ 👑 VIP: {vip_line}"
    )


# ---------------------------------------------------------------------------
# Работа со звёздочками (колонка pl_gold — именно там хранит cmd_b.py)
# ---------------------------------------------------------------------------

def _get_stars(user_id_fmt: str) -> int:
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        c = conn.cursor()
        c.execute("SELECT pl_gold FROM users WHERE user_id = ?", (user_id_fmt,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] is not None else 0
    except Exception:
        return 0


def _update_stars(user_id_fmt: str, delta: int):
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        c = conn.cursor()
        c.execute(
            "UPDATE users SET pl_gold = MAX(0, COALESCE(pl_gold, 0) + ?) WHERE user_id = ?",
            (delta, user_id_fmt),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _reset_all_stars():
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        c = conn.cursor()
        c.execute("UPDATE users SET pl_gold = 0")
        conn.commit()
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /чек — просмотр профиля пользователя
# ---------------------------------------------------------------------------

@router.message(Command("чек", "Чек"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_check(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer(
            "ℹ️ Введите ID или @username:\n"
            "<code>/чек 1234567</code>  или  <code>/чек @username</code>",
            parse_mode="HTML",
        )

    target_arg = command.args.strip().replace("@", "")

    if target_arg.isdigit():
        search_id  = f"@{target_arg}"
        display_id = target_arg
    else:
        row = database.get_user_by_username(target_arg)
        if not row:
            return await message.answer(
                f"❌ Юзернейм <code>@{target_arg}</code> не найден в базе.",
                parse_mode="HTML",
            )
        search_id  = row[0]
        display_id = search_id.replace("@", "")

    user_data = database.get_user_info(search_id)
    if not user_data:
        return await message.answer(
            f"❌ Пользователь <code>{search_id}</code> не найден.",
            parse_mode="HTML",
        )

    name, balance, _, _ = user_data
    stars     = _get_stars(search_id)
    is_banned = database.is_user_banned(display_id)
    has_vip   = database.get_vip_status(display_id)

    await message.answer(
        build_profile_text(display_id, name, balance, stars, is_banned, has_vip),
        reply_markup=get_check_kb(display_id, is_banned, has_vip),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Обработка всех кнопок карточки
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("check_"), F.from_user.id.in_(ADMIN_IDS))
async def handle_check_buttons(call: CallbackQuery, state: FSMContext):
    data = call.data  # полный callback_data

    # ── Обнулить звёзды ВСЕМ — отдельная проверка без split ──────────────
    if data == "check_resetallstars":
        _reset_all_stars()
        await call.answer("✅ Звёзды обнулены у всех пользователей!", show_alert=True)
        return

    # Убираем префикс "check_" и разбиваем
    raw    = data[len("check_"):]   # "add_balance_12345" / "ban_12345" / "refresh_12345"
    parts  = raw.split("_")
    action = parts[0]

    # ── Ввод суммы (balance или stars) ───────────────────────────────────
    if action in ("add", "rem"):
        currency = parts[1]   # "balance" или "stars"
        target   = parts[2]
        await state.update_data(t_id=target, action=action, curr=currency)
        await state.set_state(AdminStates.wait_for_amount)

        verb  = "начисления" if action == "add" else "списания"
        label = "VIRTEX" if currency == "balance" else "звёздочек"
        icon  = "💰" if currency == "balance" else "⭐️"
        return await call.message.answer(
            f"{icon} Введите сумму {verb} <b>{label}</b> для <code>@{target}</code>:",
            parse_mode="HTML",
        )

    # ── Обновить карточку ─────────────────────────────────────────────────
    if action == "refresh":
        target    = parts[1]
        search_id = f"@{target}"
        user_data = database.get_user_info(search_id)
        if not user_data:
            return await call.answer("❌ Пользователь не найден.")
        name, balance, _, _ = user_data
        stars     = _get_stars(search_id)
        is_banned = database.is_user_banned(target)
        has_vip   = database.get_vip_status(target)
        await call.message.edit_text(
            build_profile_text(target, name, balance, stars, is_banned, has_vip),
            reply_markup=get_check_kb(target, is_banned, has_vip),
            parse_mode="HTML",
        )
        await call.answer("🔄 Обновлено")
        return

    # ── Бан / VIP ─────────────────────────────────────────────────────────
    target = parts[1]
    if action == "ban":
        database.set_ban_status(f"@{target}", 1)
    elif action == "unban":
        database.set_ban_status(f"@{target}", 0)
    elif action == "givip":
        database.give_vip_month(target)
    elif action == "revip":
        database.remove_vip(target)
    else:
        return await call.answer("⚠️ Неизвестное действие.")

    await call.answer("✅ Выполнено!")

    # Перерисовываем карточку
    search_id = f"@{target}"
    user_data = database.get_user_info(search_id)
    name, balance, _, _ = user_data
    stars     = _get_stars(search_id)
    is_banned = database.is_user_banned(target)
    has_vip   = database.get_vip_status(target)

    await call.message.edit_text(
        build_profile_text(target, name, balance, stars, is_banned, has_vip),
        reply_markup=get_check_kb(target, is_banned, has_vip),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Обработка ввода суммы
# ---------------------------------------------------------------------------

@router.message(AdminStates.wait_for_amount)
async def proc_admin_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("❌ Введите целое положительное число!")

    data      = await state.get_data()
    target_id = data["t_id"]
    action    = data["action"]
    currency  = data["curr"]
    amount    = int(message.text.strip())
    fmt_id    = f"@{target_id}"

    if currency == "balance":
        delta = amount if action == "add" else -amount
        database.update_balance(fmt_id, delta)
        icon  = database.get_setting("plugs_icon", "💰")
        label = f"VIRTEX {icon}"
    else:  # stars → pl_gold
        delta = amount if action == "add" else -amount
        _update_stars(fmt_id, delta)
        icon  = database.get_setting("stars_icon", "⭐️")
        label = f"звёздочек {icon}"

    verb       = "✅ Начислено" if action == "add" else "📉 Снято"
    fmt_amount = f"{amount:,}".replace(",", " ")

    await message.answer(
        f"{verb} <b>{fmt_amount} {label}</b> пользователю <code>@{target_id}</code>",
        parse_mode="HTML",
    )
    await state.clear()
