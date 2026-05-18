from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()


def get_help_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="help_games_menu"),
         InlineKeyboardButton(text="📜 Команды", callback_data="help_cmds")],
    ])


def get_help_games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Рулетка", callback_data="help_game_roulette"),
         InlineKeyboardButton(text="💣 Мины", callback_data="help_game_mines")],
        [InlineKeyboardButton(text="🚀 Краш", callback_data="help_game_crash"),
         InlineKeyboardButton(text="🥇 Золото", callback_data="help_game_gold")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")],
    ])


def get_back_kb(target: str = "help_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]
    ])


TEXT_MAIN = "❓ <b>Справочник по боту</b>\n\nВыберите интересующий раздел ниже:"

TEXT_GAMES_MENU = "<b>🎮 Доступные игры</b>\n\nВыберите игру ниже, чтобы узнать правила и как делать ставки:"

TEXT_GAME_ROULETTE = (
    "<b>🎰 Игра: Рулетка</b>\n\n"
    "<b>Типы ставок:</b>\n"
    "• <code>рул 5000 кра</code> — ставка на красное\n"
    "• <code>рул 5000 чер</code> — ставка на черное\n"
    "• <code>рул 5000 чет</code> — ставка на четное\n"
    "• <code>рул 5000 нечет</code> — ставка на нечетное\n"
    "• <code>рул 5000 зеро</code> — ставка на зеро"
)

TEXT_GAME_MINES = (
    "<b>💣 Игра: Мины</b>\n\n"
    "Классическая игра в сапера. Чем больше мин обходите, тем выше множитель!\n\n"
    "<b>Как играть:</b>\n"
    "<code>мины 500 3</code> — ставка 500 VIRTEX, 3 мины на поле\n\n"
    "<b>Множители:</b>\n"
    "• 1 мина — до x4.72\n"
    "• 3 мины — до x7.38\n"
    "• 5 мин — до x14.92\n\n"
    "Открывайте безопасные клетки и забирайте выигрыш!"
)

TEXT_GAME_CRASH = (
    "<b>🚀 Игра: Краш</b>\n\n"
    "График растет, а вместе с ним и ваш выигрыш. Главное — успеть забрать деньги до того, как он обвалится!\n\n"
    "<b>Как играть:</b>\n"
    "<code>краш 500 2.5</code> — ставка 500 VIRTEX на множитель 2.5x\n\n"
    "Если множитель игры упал выше вашего — вы выиграли!"
)

TEXT_GAME_GOLD = (
    "<b>🥇 Игра: Золото</b>\n\n"
    "Проходите уровни, выбирая безопасную ячейку. Каждый новый уровень увеличивает множитель!\n\n"
    "<b>Как играть:</b>\n"
    "<code>золото 500</code> — ставка 500 VIRTEX\n\n"
    "<b>Множители:</b>\n"
    "1 ур. x1.5 | 2 ур. x2.0 | 3 ур. x2.8\n"
    "4 ур. x3.8 | 5 ур. x5.2 | 6 ур. x7.0\n"
    "7 ур. x9.5 | 8 ур. x13.0 | 9 ур. x18.0\n\n"
    "На каждом уровне 2 ячейки — одна безопасная, одна мина. Выберите правильную!"
)

TEXT_CMDS = (
    "<b>📜 Основные команды:</b>\n\n"
    "• <code>топ</code> — мировой топ пользователей по балансу\n"
    "• <code>топ ч</code> — топ пользователей в этом чате\n"
    "• <code>б</code> — проверить баланс\n"
    "• <code>дать 100 @username</code> — передать VIRTEX другому\n"
    "• <code>банк</code> — банковская система (депозиты)\n"
    "• <code>донат</code> — пополнение баланса\n"
    "• <code>🎁 Бонус</code> — получить ежедневный бонус"
)


@router.message(F.text.lower().in_({"игры", "помощь", "команды", "❓ помощь", "help"}))
async def cmd_help(message: Message):
    await message.answer(TEXT_MAIN, reply_markup=get_help_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "help_main")
async def call_help_main(call: CallbackQuery):
    await call.message.edit_text(TEXT_MAIN, reply_markup=get_help_main_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_cmds")
async def call_help_cmds(call: CallbackQuery):
    await call.message.edit_text(TEXT_CMDS, reply_markup=get_back_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_games_menu")
async def call_help_games_menu(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAMES_MENU, reply_markup=get_help_games_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_roulette")
async def call_help_game_roulette(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_ROULETTE, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_mines")
async def call_help_game_mines(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_MINES, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_crash")
async def call_help_game_crash(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_CRASH, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "help_game_gold")
async def call_help_game_gold(call: CallbackQuery):
    await call.message.edit_text(TEXT_GAME_GOLD, reply_markup=get_back_kb("help_games_menu"), parse_mode="HTML")
    await call.answer()
