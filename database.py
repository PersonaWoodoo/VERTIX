import sqlite3
import datetime
import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ==================== НАСТРОЙКА ПУТИ К БАЗЕ ДАННЫХ ====================
# Если переменная окружения DB_PATH не задана, используется файл bot_db.sqlite в папке с ботом
DB_PATH = os.getenv("DB_PATH", "bot_db.sqlite")

# Создаём папку для базы данных, если её нет
db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir)

# ==================== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ ====================

def _apply_pragma(conn: sqlite3.Connection):
    """Применяет оптимальные настройки SQLite"""
    try:
        conn.execute("PRAGMA journal_mode=WAL;")        # WAL режим для лучшей производительности
        conn.execute("PRAGMA synchronous=NORMAL;")     # Баланс скорости и безопасности
        conn.execute("PRAGMA foreign_keys=ON;")        # Проверка внешних ключей
        conn.execute("PRAGMA cache_size=-65536")       # 64MB кэш
        conn.execute("PRAGMA temp_store=MEMORY")       # Временные таблицы в памяти
        conn.execute("PRAGMA busy_timeout=30000")      # 30 секунд ожидания при блокировке
    except Exception as e:
        logger.error(f"Ошибка при применении pragma: {e}")


def _connect(timeout: int = 30, retries: int = 5) -> sqlite3.Connection:
    """
    Создаёт соединение с БД с повторными попытками при блокировке
    """
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=timeout)
            _apply_pragma(conn)
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                wait = 0.5 * (attempt + 1)
                time.sleep(wait)
                continue
            raise
    raise sqlite3.OperationalError(f"Не удалось подключиться к БД после {retries} попыток")


@contextmanager
def get_db_connection(timeout: int = 30):
    """
    Контекстный менеджер для работы с БД.
    Автоматически закрывает соединение и делает commit/rollback.
    """
    conn = None
    try:
        conn = _connect(timeout)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


# ==================== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ====================

def _migrate(c: sqlite3.Cursor):
    """Безопасное добавление новых колонок (миграции)"""
    migrations = [
        ("users", "pl_gold INTEGER DEFAULT 0"),
        ("users", "stars INTEGER DEFAULT 0"),
        ("users", "hide_mention INTEGER DEFAULT 0"),
        ("users", "custom_nickname TEXT"),
        ("users", "custom_nick TEXT"),
        ("users", "joined_date TEXT"),
        ("users", "vip_until TEXT"),
        ("users", "registered_at TEXT"),
        ("users", "rep_plus INTEGER DEFAULT 0"),
        ("users", "rep_minus INTEGER DEFAULT 0"),
        ("users", "is_bot INTEGER DEFAULT 0"),
        ("group_settings", "basket_status INTEGER DEFAULT 1"),
        ("group_settings", "crash_status INTEGER DEFAULT 1"),
        ("group_settings", "mines_status INTEGER DEFAULT 1"),
        ("group_rules", "rules_entities TEXT"),
    ]
    for table, column_def in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует


def init_db():
    """
    Инициализация базы данных.
    Вызывается 1 раз при запуске бота.
    Если база уже существует, создаёт только отсутствующие таблицы.
    """
    with get_db_connection() as conn:
        c = conn.cursor()

        # Основные таблицы
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT UNIQUE,
                name            TEXT,
                username        TEXT,
                registered_at   TEXT,
                balance         INTEGER DEFAULT 0,
                pl_gold         INTEGER DEFAULT 0,
                is_banned       INTEGER DEFAULT 0,
                last_bonus      TEXT,
                roulette_total_won INTEGER DEFAULT 0,
                rep_plus        INTEGER DEFAULT 0,
                rep_minus       INTEGER DEFAULT 0,
                stars           INTEGER DEFAULT 0,
                custom_nickname TEXT,
                vip_until       TEXT
            );

            CREATE TABLE IF NOT EXISTS rep_limits (
                user_id     INTEGER PRIMARY KEY,
                count       INTEGER DEFAULT 0,
                last_reset  TEXT
            );

            CREATE TABLE IF NOT EXISTS group_kazna (
                chat_id         INTEGER PRIMARY KEY,
                balance         INTEGER DEFAULT 0,
                reward_per_user INTEGER DEFAULT 0,
                status          INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_stats (
                chat_id         INTEGER,
                user_id         INTEGER,
                message_count   INTEGER DEFAULT 0,
                total_messages  INTEGER DEFAULT 0,
                last_reset      DATE DEFAULT (CURRENT_DATE),
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS exchange_rate (
                id   INTEGER PRIMARY KEY,
                rate INTEGER DEFAULT 2450
            );

            CREATE TABLE IF NOT EXISTS invited_users (
                chat_id    INTEGER,
                invited_id INTEGER,
                inviter_id INTEGER,
                PRIMARY KEY (chat_id, invited_id)
            );

            CREATE TABLE IF NOT EXISTS mine_games (
                user_id        INTEGER,
                chat_id        INTEGER,
                message_id     INTEGER,
                bet            INTEGER,
                mines_map      TEXT,
                revealed_cells TEXT,
                last_action    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id         INTEGER PRIMARY KEY,
                roulette_status INTEGER DEFAULT 1,
                mines_status    INTEGER DEFAULT 1,
                crash_status    INTEGER DEFAULT 1,
                casino_balance  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS promos (
                code          TEXT PRIMARY KEY,
                amount        INTEGER NOT NULL,
                max_uses      INTEGER NOT NULL,
                current_uses  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS group_rules (
                chat_id    INTEGER PRIMARY KEY,
                rules_text TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS promo_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                promo_code TEXT NOT NULL,
                timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_code) REFERENCES promos(code)
            );

            CREATE TABLE IF NOT EXISTS transfers (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id   TEXT,
                from_name TEXT,
                to_id     TEXT,
                to_name   TEXT,
                amount    INTEGER,
                type      TEXT,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS roulette_bets (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER,
                chat_id   INTEGER,
                user_name TEXT,
                amount    INTEGER,
                type      TEXT,
                value     TEXT
            );

            CREATE TABLE IF NOT EXISTS roulette_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER,
                number    INTEGER,
                color     TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS global_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS tournament_stats (
                user_id   INTEGER PRIMARY KEY,
                user_name TEXT,
                profit    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tournament_history (
                place     INTEGER,
                user_id   INTEGER,
                user_name TEXT,
                profit    INTEGER
            );

            CREATE TABLE IF NOT EXISTS referrals (
                invitee_id INTEGER PRIMARY KEY,
                inviter_id INTEGER NOT NULL,
                date_time  TEXT NOT NULL
            );
        """)

        # Индексы для ускорения запросов
        c.executescript("""
            CREATE INDEX IF NOT EXISTS idx_roulette_bets_chat ON roulette_bets(chat_id);
            CREATE INDEX IF NOT EXISTS idx_roulette_bets_user_chat ON roulette_bets(user_id, chat_id);
            CREATE INDEX IF NOT EXISTS idx_roulette_history_chat ON roulette_history(chat_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
            CREATE INDEX IF NOT EXISTS idx_transfers_from_id ON transfers(from_id);
            CREATE INDEX IF NOT EXISTS idx_transfers_to_id ON transfers(to_id);
        """)

        # Настройки по умолчанию
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('page_history_emoji', '📄')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('plugs_icon', '💰')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('stars_icon', '⭐️')")
        c.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('crash_prefix', '🚀')")
        c.execute("INSERT OR IGNORE INTO exchange_rate (id, rate) VALUES (1, 2450)")

        # Миграции для существующей базы
        _migrate(c)

        conn.commit()
        logger.info(f"База данных инициализирована: {DB_PATH}")
        print(f"✅ База данных: {DB_PATH}")


# ==================== ОСНОВНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ====================

def add_user(user_id: int, name: str, username: str):
    """Добавляет или обновляет пользователя"""
    fmt_user_id = f"@{user_id}"
    fmt_username = f"@{username}" if username else "Нет"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, username FROM users WHERE user_id = ?", (fmt_user_id,))
            row = c.fetchone()
            if not row:
                c.execute(
                    "INSERT INTO users (user_id, name, username, registered_at, balance) VALUES (?, ?, ?, ?, 0)",
                    (fmt_user_id, name, fmt_username, current_time),
                )
            else:
                db_name, db_username = row
                if db_name != name or db_username != fmt_username:
                    c.execute(
                        "UPDATE users SET name = ?, username = ? WHERE user_id = ?",
                        (name, fmt_username, fmt_user_id),
                    )
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка в add_user: {e}")


def get_balance(user_id: int) -> int:
    """Получает баланс пользователя"""
    fmt_user_id = f"@{user_id}"
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT balance FROM users WHERE user_id = ?", (fmt_user_id,))
            result = c.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Ошибка получения баланса: {e}")
        return 0


def update_balance(user_id: str, amount: int):
    """Обновляет баланс (user_id в формате @12345)"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления баланса: {e}")


def is_user_banned(user_id: int) -> bool:
    """Проверяет, забанен ли пользователь"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT is_banned FROM users WHERE user_id = ?", (f"@{user_id}",))
            res = c.fetchone()
            return bool(res[0]) if res else False
    except Exception as e:
        logger.error(f"Ошибка проверки бана: {e}")
        return False


def set_ban_status(user_id: str, status: int):
    """Устанавливает статус бана"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка установки бана: {e}")


def get_user_bonus_info(user_id: int):
    """Получает информацию о последнем бонусе"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT last_bonus FROM users WHERE user_id = ?", (f"@{user_id}",))
            res = c.fetchone()
            return res[0] if res else None
    except Exception as e:
        logger.error(f"Ошибка получения бонуса: {e}")
        return None


def give_bonus(user_id: int, amount: int):
    """Выдаёт бонус пользователю"""
    now = datetime.datetime.now().isoformat()
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?",
                (amount, now, f"@{user_id}"),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка выдачи бонуса: {e}")


def get_vip_status(user_id: int) -> bool:
    """Проверяет статус VIP"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT vip_until FROM users WHERE user_id = ?", (f"@{user_id}",))
            res = c.fetchone()
            if res and res[0]:
                from datetime import datetime
                return datetime.fromisoformat(res[0]) > datetime.now()
            return False
    except Exception as e:
        logger.error(f"Ошибка проверки VIP: {e}")
        return False


def give_vip_month(user_id: int):
    """Выдаёт VIP на месяц"""
    from datetime import datetime, timedelta
    new_until = (datetime.now() + timedelta(days=30)).isoformat()
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_until, f"@{user_id}"))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка выдачи VIP: {e}")


def remove_vip(user_id: int):
    """Снимает VIP статус"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET vip_until = NULL WHERE user_id = ?", (f"@{user_id}",))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка снятия VIP: {e}")


def get_user_info(target_id: str):
    """Получает информацию о пользователе"""
    clean_id = target_id.replace("@", "")
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, balance, pl_gold, vip_until FROM users WHERE user_id = ?", (f"@{clean_id}",))
            return c.fetchone()
    except Exception as e:
        logger.error(f"Ошибка получения информации: {e}")
        return None


def get_user_by_username(username: str):
    """Ищет пользователя по username"""
    clean_username = username if username.startswith("@") else f"@{username}"
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT user_id, name FROM users WHERE username = ?", (clean_username,))
            return c.fetchone()
    except Exception as e:
        logger.error(f"Ошибка поиска по юзернейму: {e}")
        return None


def update_user_info(user_id, name, username):
    """Обновляет информацию о пользователе"""
    fmt_user_id = f"@{user_id}" if not str(user_id).startswith("@") else user_id
    fmt_username = f"@{username}" if username else "Нет"
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET name = ?, username = ? WHERE user_id = ?", (name, fmt_username, fmt_user_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления информации: {e}")


def get_full_user(user_id: int):
    """Получает полную информацию о пользователе"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, custom_nickname, registered_at, rep_plus, rep_minus FROM users WHERE user_id = ?", (f"@{user_id}",))
            return c.fetchone()
    except Exception as e:
        logger.error(f"Ошибка получения полной информации: {e}")
        return None


def get_setting(key: str, default_value=None):
    """Получает настройку"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = ?", (key,))
            result = c.fetchone()
            return result[0] if result else default_value
    except Exception:
        return default_value


def set_setting(key: str, value: str):
    """Устанавливает настройку"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка установки настройки: {e}")


def get_global_emoji() -> str:
    """Получает глобальный эмодзи для истории"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = 'global_history_emoji'")
            row = c.fetchone()
            return row[0] if row else "🌕"
    except Exception:
        return "🌕"


def set_global_emoji(emoji_text: str):
    """Устанавливает глобальный эмодзи для истории"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_history_emoji', ?)", (emoji_text,))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка установки эмодзи: {e}")


def get_page_emoji() -> str:
    """Получает эмодзи для страниц истории"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = 'page_history_emoji'")
            row = c.fetchone()
            return row[0] if row else "🧱"
    except Exception:
        return "🧱"


def set_page_emoji(emoji_text: str):
    """Устанавливает эмодзи для страниц истории"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('page_history_emoji', ?)", (emoji_text,))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка установки эмодзи страниц: {e}")


def get_history(user_id: int):
    """Получает историю транзакций пользователя"""
    u_id = f"@{user_id}"
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT amount, from_name, to_name, timestamp, from_id, to_id, type 
                FROM transfers 
                WHERE to_id = ? OR from_id = ? 
                ORDER BY id DESC LIMIT 20
            """, (u_id, u_id))
            return c.fetchall()
    except Exception as e:
        logger.error(f"Ошибка получения истории: {e}")
        return []


def make_transfer(from_user_id: int, from_name: str, to_user_id: int, to_name: str, amount: int, currency: str = "balance") -> bool:
    """Выполняет перевод средств"""
    if currency not in ("balance", "gold"):
        return False

    db_column = "pl_gold" if currency == "gold" else "balance"
    f_id = f"@{from_user_id}"
    t_id = f"@{to_user_id}"

    try:
        with get_db_connection(timeout=20) as conn:
            c = conn.cursor()
            c.execute(f"SELECT {db_column} FROM users WHERE user_id = ?", (f_id,))
            res = c.fetchone()
            if not res or (res[0] or 0) < amount:
                return False

            c.execute(f"UPDATE users SET {db_column} = {db_column} - ? WHERE user_id = ?", (amount, f_id))
            c.execute("INSERT OR IGNORE INTO users (user_id, name, balance) VALUES (?, ?, 0)", (t_id, to_name))
            c.execute(f"UPDATE users SET {db_column} = {db_column} + ? WHERE user_id = ?", (amount, t_id))

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO transfers (from_id, from_name, to_id, to_name, amount, type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f_id, from_name, t_id, to_name, amount, f"transfer_{currency}", now),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка в make_transfer: {e}")
        return False


def log_donate(user_id: int, payment_id: str, amount: int, stars: int, currency: str = "balance") -> bool:
    """Логирует донат в историю транзакций"""
    db_column = "balance" if currency == "balance" else "pl_gold"
    f_id = f"@{user_id}"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO transfers (from_id, from_name, to_id, to_name, amount, type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("SYSTEM", "SYSTEM", f_id, f"Stars: {stars}", amount, "donate", now),
            )
            c.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (f_id, "Пользователь"))
            c.execute(f"UPDATE users SET {db_column} = {db_column} + ? WHERE user_id = ?", (amount, f_id))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка в log_donate: {e}")
        return False


# Для обратной совместимости со старыми вызовами
DB_NAME = DB_PATH
