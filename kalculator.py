import html
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message
from database import DB_PATH  # Путь к вашей БД
import database # Добавлено для совместимости с вашими методами настроек

router = Router()

# Эмодзи по умолчанию, если в БД еще ничего не настроено
DEFAULT_CALC_EMOJI = "💬"

def calculate_expression(expression: str):
    """Безопасно вычисляет математическое выражение."""
    expression = expression.replace(',', '.')
    allowed_chars = "0123456789+-*/(). "
    if not all(char in allowed_chars for char in expression):
        return None
    try:
        # Ограничиваем eval для безопасности
        result = eval(expression, {"__builtins__": None}, {})
        if isinstance(result, float) and result.is_integer():
            return int(result)
        return result
    except Exception:
        return None

async def get_calc_emoji() -> str:
    """Получает сохраненный эмодзи из базы данных."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                    "SELECT value FROM mine_settings WHERE key = 'calc_emoji'"
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else DEFAULT_CALC_EMOJI
    except Exception:
        return DEFAULT_CALC_EMOJI

# КОМАНДА ИЗМЕНЕНА НА "реши"
@router.message(F.text.lower().startswith("реши"))
async def cmd_calculate(message: Message):
    # Разбиваем строку: "реши" и само "выражение"
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply(
            "Введите выражение, например: <code>реши 5 * 5</code>",
            parse_mode="HTML"
        )

    expression = parts[1].strip()
    result = calculate_expression(expression)

    # Получаем актуальный эмодзи
    current_emoji = await get_calc_emoji()

    # Данные пользователя
    user_name = html.escape(message.from_user.first_name)
    mention = f'<a href="tg://user?id={message.from_user.id}">{user_name}</a>'

    if result is not None:
        # Дизайн сохранен полностью
        response_text = (
            f"{mention}, <b>вот ваше решение</b>\n\n"
            f"{current_emoji}:решение: <code>{expression} = {result}</code>"
        )
        await message.reply(response_text, parse_mode="HTML")
    else:
        await message.reply(
            f"{mention}, <b>ошибка в выражении!</b>",
            parse_mode="HTML"
        )

@router.message(F.text.lower().startswith("/spiem "))
async def cmd_set_calc_emoji(message: Message):
    # Проверка на владельца (согласно вашим предыдущим правкам)
    member = await message.chat.get_member(message.from_user.id)
    if member.status != "creator":
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Используйте: <code>/spiem [эмодзи]</code>", parse_mode="HTML")

    new_emoji = parts[1].strip()

    # Обработка кастомных эмодзи
    if message.entities:
        for ent in message.entities:
            if ent.type == "custom_emoji":
                placeholder = ent.extract_from(message.text)
                new_emoji = f'<tg-emoji emoji-id="{ent.custom_emoji_id}">{placeholder}</tg-emoji>'
                break

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO mine_settings (key, value) VALUES ('calc_emoji', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (new_emoji,))
        await db.commit()

    await message.reply(f"✅ Эмодзи калькулятора обновлен на: {new_emoji}", parse_mode="HTML")
