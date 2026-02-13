import asyncio
import logging
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramBadRequest

# --------------------- НАСТРОЙКИ ---------------------
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # ← @PulsSupport
ADMIN_IDS = [123456789, 987654321]  # ← твои ID
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

# Настройки анти-спама
MESSAGE_COOLDOWN = 60  # секунд
SPAM_LIMIT = 5  # сообщений без ответа
SPAM_BLOCK_TIME = 600  # 10 минут в секундах
TICKET_AUTO_CLOSE_HOURS = 48  # часов без активности

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица тикетов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            first_name TEXT,
            category TEXT DEFAULT 'question',
            created_at TEXT NOT NULL,
            last_message_at TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            has_responded INTEGER DEFAULT 0,
            closed_at TEXT,
            closed_by INTEGER,
            blocked_until TEXT,
            rating INTEGER,
            feedback_text TEXT
        )
    ''')
    
    # Таблица админов поддержки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_admins (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            last_active TEXT
        )
    ''')
    
    # Таблица сообщений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT,
            media_group_id TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    ''')
    
    # Таблица для альбомов (медиа групп)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_groups (
            group_id TEXT NOT NULL,
            ticket_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            caption TEXT,
            timestamp TEXT NOT NULL,
            PRIMARY KEY (group_id, message_id)
        )
    ''')
    
    # Индексы для быстрого поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_ticket_id ON messages(ticket_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_groups_group_id ON media_groups(group_id)')
    
    conn.commit()
    conn.close()

init_db()

# --------------------- СОСТОЯНИЯ FSM ---------------------
class AdminRegistration(StatesGroup):
    waiting_for_name = State()

class AdminEditName(StatesGroup):
    waiting_for_new_name = State()

class TicketStates(StatesGroup):
    in_dialog = State()
    waiting_category = State()
    waiting_feedback = State()

class TicketClose(StatesGroup):
    waiting_confirmation = State()

# --------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------------
def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS

def get_admin_name(user_id: int) -> Optional[str]:
    """Получение имени админа по ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_admin_name(user_id: int, display_name: str):
    """Сохранение имени админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO support_admins (user_id, display_name, registered_at, last_active)
        VALUES (?, ?, COALESCE((SELECT registered_at FROM support_admins WHERE user_id = ?), ?), ?)
    """, (user_id, display_name, user_id, now, now))
    conn.commit()
    conn.close()

def update_admin_activity(user_id: int):
    """Обновление времени последней активности админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("UPDATE support_admins SET last_active = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()

def get_or_create_ticket(user: types.User, category: str = 'question') -> int:
    """Получение или создание тикета для пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, status FROM tickets WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    
    now = datetime.utcnow().isoformat()
    
    if row:
        ticket_id = row[0]
        status = row[1]
        
        # Если тикет закрыт, создаем новый
        if status == 'closed':
            cursor.execute("""
                INSERT INTO tickets (user_id, username, first_name, category, created_at, last_message_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'open')
            """, (user.id, user.username, user.first_name, category, now, now))
            ticket_id = cursor.lastrowid
        else:
            cursor.execute("UPDATE tickets SET last_message_at = ?, username = ?, first_name = ? WHERE id = ?",
                           (now, user.username, user.first_name, ticket_id))
    else:
        cursor.execute("""
            INSERT INTO tickets (user_id, username, first_name, category, created_at, last_message_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'open')
        """, (user.id, user.username, user.first_name, category, now, now))
        ticket_id = cursor.lastrowid
        
        # Уведомление админов о новом тикете
        asyncio.create_task(notify_admins_new_ticket(user, ticket_id, category))
    
    conn.commit()
    conn.close()
    return ticket_id

async def notify_admins_new_ticket(user: types.User, ticket_id: int, category: str):
    """Уведомление админов о новом тикете"""
    category_names = {
        'question': '❓ Вопрос',
        'problem': '⚠️ Проблема',
        'suggestion': '💡 Предложение',
        'other': '📌 Другое'
    }
    
    category_text = category_names.get(category, category)
    
    text = (
        f"🆕 <b>НОВЫЙ ТИКЕТ #{ticket_id}</b>\n\n"
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📱 Username: @{user.username or 'нет'}\n"
        f"📂 Категория: {category_text}\n"
        f"⏰ Время: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n\n"
        f"Для ответа используйте /reply {ticket_id}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Ошибка уведомления админа {admin_id}: {e}")

def check_spam_block(user_id: int) -> tuple[bool, Optional[str]]:
    """Проверка на спам-блок"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT blocked_until FROM tickets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        blocked_until = datetime.fromisoformat(row[0])
        if datetime.utcnow() < blocked_until:
            remaining = (blocked_until - datetime.utcnow()).seconds // 60
            return True, f"⛔ Вы заблокированы на {remaining} мин. за спам."
    
    return False, None

def check_message_cooldown(user_id: int) -> tuple[bool, Optional[str]]:
    """Проверка кулдауна между сообщениями"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT last_message_at FROM tickets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        last_time = datetime.fromisoformat(row[0])
        diff = datetime.utcnow() - last_time
        if diff.total_seconds() < MESSAGE_COOLDOWN:
            remaining = int(MESSAGE_COOLDOWN - diff.total_seconds())
            return True, f"⏳ Подождите {remaining} сек. перед следующим сообщением."
    
    return False, None

def check_message_limit(user_id: int) -> tuple[bool, Optional[str]]:
    """Проверка лимита сообщений без ответа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM messages m
        JOIN tickets t ON m.ticket_id = t.id
        WHERE t.user_id = ? AND m.sender_type = 'user' 
        AND t.has_responded = 0 AND t.status = 'open'
        AND m.timestamp > datetime('now', '-1 hour')
    """, (user_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    if count >= SPAM_LIMIT:
        # Блокируем пользователя
        block_until = datetime.utcnow() + timedelta(seconds=SPAM_BLOCK_TIME)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE tickets SET blocked_until = ? WHERE user_id = ?", 
                      (block_until.isoformat(), user_id))
        conn.commit()
        conn.close()
        
        return True, f"⛔ Вы заблокированы на 10 минут за отправку более {SPAM_LIMIT} сообщений без ответа."
    
    return False, None

def update_message_time(user_id: int):
    """Обновление времени последнего сообщения"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("UPDATE tickets SET last_message_at = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()

def get_ticket_status(user_id: int) -> Optional[tuple]:
    """Получение статуса тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT status, has_responded FROM tickets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def update_has_responded(user_id: int):
    """Обновление флага ответа админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET has_responded = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def reset_has_responded(user_id: int):
    """Сброс флага ответа админа (для нового сообщения пользователя)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET has_responded = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, media_group_id: str = None):
    """Сохранение сообщения в БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT INTO messages (ticket_id, sender_type, sender_id, content, media_group_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (ticket_id, sender_type, sender_id, content, media_group_id, now))
    conn.commit()
    conn.close()

def save_media_group(group_id: str, ticket_id: int, message_id: int, file_id: str, media_type: str, caption: str = None):
    """Сохранение медиа группы в БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO media_groups (group_id, ticket_id, message_id, file_id, media_type, caption, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (group_id, ticket_id, message_id, file_id, media_type, caption, now))
    conn.commit()
    conn.close()

def get_media_group(group_id: str) -> List[tuple]:
    """Получение всех медиа из группы"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, media_type, caption FROM media_groups 
        WHERE group_id = ? ORDER BY message_id ASC
    ''', (group_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_ticket_messages(ticket_id: int) -> List:
    """Получение всех сообщений тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sender_type, content, timestamp, media_group_id 
        FROM messages 
        WHERE ticket_id = ? 
        ORDER BY timestamp ASC
    ''', (ticket_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_admin_tickets(admin_id: int) -> List:
    """Получение тикетов, в которых участвовал админ"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT t.id, t.user_id, t.username, t.status, t.created_at, t.last_message_at
        FROM tickets t
        JOIN messages m ON t.id = m.ticket_id
        WHERE m.sender_type = 'admin' AND m.sender_id = ?
        ORDER BY t.last_message_at DESC
    ''', (admin_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_open_tickets() -> List:
    """Получение всех открытых тикетов"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, username, first_name, category, created_at, last_message_at
        FROM tickets
        WHERE status = 'open'
        ORDER BY created_at ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_admin_profile(admin_id: int) -> str:
    """Получение профиля админа"""
    name = get_admin_name(admin_id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT registered_at, last_active,
               (SELECT COUNT(*) FROM messages WHERE sender_id = ? AND sender_type = 'admin') as total_replies
        FROM support_admins WHERE user_id = ?
    """, (admin_id, admin_id))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        registered = datetime.fromisoformat(row[0]).strftime('%d.%m.%Y %H:%M')
        last_active = datetime.fromisoformat(row[1]).strftime('%d.%m.%Y %H:%M') if row[1] else 'никогда'
        total_replies = row[2]
        
        return (
            f"👤 <b>Профиль поддержки</b>\n\n"
            f"📋 Имя: {name}\n"
            f"🆔 ID: <code>{admin_id}</code>\n"
            f"📅 Зарегистрирован: {registered}\n"
            f"⏰ Последняя активность: {last_active}\n"
            f"💬 Всего ответов: {total_replies}"
        )
    
    return f"Профиль поддержки\n\nИмя: {name}\nID: {admin_id}"

def delete_admin_account(admin_id: int):
    """Удаление аккаунта админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM support_admins WHERE user_id = ?", (admin_id,))
    conn.commit()
    conn.close()

def close_ticket(ticket_id: int, closed_by: int):
    """Закрытие тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE tickets 
        SET status = 'closed', closed_at = ?, closed_by = ? 
        WHERE id = ? AND status != 'closed'
    """, (now, closed_by, ticket_id))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def auto_close_old_tickets():
    """Автоматическое закрытие старых тикетов"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cutoff = (datetime.utcnow() - timedelta(hours=TICKET_AUTO_CLOSE_HOURS)).isoformat()
    
    cursor.execute("""
        SELECT id, user_id FROM tickets 
        WHERE status = 'open' AND last_message_at < ?
    """, (cutoff,))
    
    old_tickets = cursor.fetchall()
    
    for ticket_id, user_id in old_tickets:
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = ?, closed_by = ? 
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), 0, ticket_id))
        
        # Уведомление пользователя
        try:
            asyncio.create_task(bot.send_message(
                user_id,
                f"⏰ Ваше обращение #{ticket_id} автоматически закрыто из-за отсутствия активности в течение {TICKET_AUTO_CLOSE_HOURS} часов.\n\n"
                f"Если вопрос остался актуален, напишите новое сообщение."
            ))
        except:
            pass
    
    conn.commit()
    conn.close()
    return len(old_tickets)

def save_rating(ticket_id: int, rating: int, feedback: str = None):
    """Сохранение оценки тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET rating = ?, feedback_text = ? WHERE id = ?", 
                  (rating, feedback, ticket_id))
    conn.commit()
    conn.close()

def get_statistics() -> Dict[str, Any]:
    """Получение статистики поддержки"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    stats = {}
    
    # Общая статистика
    cursor.execute("SELECT COUNT(*) FROM tickets")
    stats['total_tickets'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'")
    stats['open_tickets'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed'")
    stats['closed_tickets'] = cursor.fetchone()[0]
    
    # Оценки
    cursor.execute("SELECT AVG(rating) FROM tickets WHERE rating IS NOT NULL")
    avg_rating = cursor.fetchone()[0]
    stats['avg_rating'] = round(avg_rating, 1) if avg_rating else 0
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 5")
    stats['rating_5'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 4")
    stats['rating_4'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 3")
    stats['rating_3'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 2")
    stats['rating_2'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 1")
    stats['rating_1'] = cursor.fetchone()[0]
    
    # Время ответа
    cursor.execute("""
        SELECT AVG(
            strftime('%s', m.timestamp) - strftime('%s', t.created_at)
        ) FROM tickets t
        JOIN messages m ON t.id = m.ticket_id
        WHERE m.sender_type = 'admin' AND m.id = (
            SELECT MIN(id) FROM messages 
            WHERE ticket_id = t.id AND sender_type = 'admin'
        )
    """)
    avg_response_time = cursor.fetchone()[0]
    stats['avg_response_seconds'] = int(avg_response_time) if avg_response_time else 0
    
    conn.close()
    return stats

# --------------------- КЛАВИАТУРЫ ---------------------
def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню для пользователя"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Написать в поддержку", callback_data="support:start")
    builder.button(text="ℹ️ Информация", callback_data="info:about")
    builder.button(text="🤖 Главный бот", url="https://t.me/PulsOfficialManager_bot")
    builder.adjust(1)
    return builder.as_markup()

def get_category_menu() -> InlineKeyboardMarkup:
    """Меню выбора категории обращения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Вопрос", callback_data="category:question")
    builder.button(text="⚠️ Проблема", callback_data="category:problem")
    builder.button(text="💡 Предложение", callback_data="category:suggestion")
    builder.button(text="📌 Другое", callback_data="category:other")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены диалога"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="support:cancel")
    return builder.as_markup()

def get_after_message_menu() -> InlineKeyboardMarkup:
    """Меню после отправки сообщения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Новое сообщение", callback_data="support:continue")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_rating_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для оценки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐️ 5 - Отлично", callback_data=f"rate:5:{ticket_id}")
    builder.button(text="⭐️ 4 - Хорошо", callback_data=f"rate:4:{ticket_id}")
    builder.button(text="⭐️ 3 - Нормально", callback_data=f"rate:3:{ticket_id}")
    builder.button(text="⭐️ 2 - Плохо", callback_data=f"rate:2:{ticket_id}")
    builder.button(text="⭐️ 1 - Ужасно", callback_data=f"rate:1:{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_menu() -> InlineKeyboardMarkup:
    """Главное меню админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Открытые тикеты", callback_data="admin:open_tickets")
    builder.button(text="📜 Моя история", callback_data="admin:history")
    builder.button(text="👤 Профиль", callback_data="admin:profile")
    builder.button(text="✏️ Изменить имя", callback_data="admin:change_name")
    builder.button(text="🔍 Поиск", callback_data="admin:search")
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="🗑️ Удалить аккаунт", callback_data="admin:delete_account")
    builder.adjust(1)
    return builder.as_markup()

def get_group_menu() -> InlineKeyboardMarkup:
    """Меню для групповых чатов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Написать в поддержку", url="https://t.me/PulsSupport_bot")
    return builder.as_markup()

def get_ticket_actions_keyboard(ticket_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий над тикетом для админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Закрыть тикет", callback_data=f"close:{ticket_id}:{user_id}")
    builder.button(text="📜 История", callback_data=f"admin:view_ticket_{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()

# --------------------- ИНИЦИАЛИЗАЦИЯ БОТА ---------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Словарь для временного хранения альбомов
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

# --------------------- КОМАНДЫ ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    if message.chat.type != 'private':
        await message.answer(
            "👋 Привет! Для вопросов и предложений пиши мне в личные сообщения.",
            reply_markup=get_group_menu()
        )
        return

    user = message.from_user

    # Проверяем, нужно ли авто-закрыть старые тикеты
    closed_count = auto_close_old_tickets()
    if closed_count > 0:
        logging.info(f"Автоматически закрыто {closed_count} старых тикетов")

    # Если админ и не зарегистрирован
    if is_admin(user.id) and not get_admin_name(user.id):
        await message.answer(
            "👋 Добро пожаловать в панель поддержки!\n\n"
            "Введите своё имя в формате:\n"
            "Имя Ф.\n\n"
            "Пример: Иван З."
        )
        await state.set_state(AdminRegistration.waiting_for_name)
        return

    # Для обычных пользователей - выбор категории
    await message.answer(
        "👋 Добро пожаловать в поддержку Puls!\n\n"
        "Выберите категорию вашего обращения:",
        reply_markup=get_category_menu()
    )

@dp.message(Command("admin_menu"))
async def admin_menu_command(message: Message):
    """Команда /admin_menu"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    update_admin_activity(message.from_user.id)
    await message.answer("🔧 <b>Меню поддержки</b>", 
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_admin_menu())

@dp.message(Command("change_name"))
async def change_name_command(message: Message, state: FSMContext):
    """Команда /change_name"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    await message.answer(
        "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminEditName.waiting_for_new_name)

@dp.message(Command("reply"))
async def reply_command(message: Message):
    """Быстрый ответ на тикет по номеру"""
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /reply <номер_тикета> <текст>")
        return
    
    try:
        ticket_id = int(args[1].split()[0])
        reply_text = ' '.join(args[1].split()[1:])
    except:
        await message.answer("Неверный формат. Пример: /reply 123 Ваш ответ")
        return
    
    if not reply_text:
        await message.answer("Введите текст ответа")
        return
    
    # Получаем user_id по ticket_id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer(f"Тикет #{ticket_id} не найден")
        return
    
    user_id = row[0]
    admin_name = get_admin_name(message.from_user.id)
    
    if not admin_name:
        await message.answer("Вы не зарегистрированы. Используйте /start")
        return
    
    try:
        prefix = f"✉️ <b>Ответ от {admin_name}</b>\n\n"
        await bot.send_message(user_id, prefix + reply_text, parse_mode=ParseMode.HTML)
        
        # Сохраняем в БД
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tickets WHERE user_id = ?", (user_id,))
        ticket_id_db = cursor.fetchone()[0]
        
        update_has_responded(user_id)
        save_message(ticket_id_db, 'admin', message.from_user.id, reply_text)
        conn.close()
        
        await message.answer(f"✅ Ответ на тикет #{ticket_id} отправлен", 
                           reply_markup=get_ticket_actions_keyboard(ticket_id, user_id))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("close"))
async def close_command(message: Message, state: FSMContext):
    """Команда /close для закрытия тикета"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /close <номер_тикета>")
        return
    
    try:
        ticket_id = int(args[1])
    except:
        await message.answer("Неверный номер тикета")
        return
    
    # Получаем информацию о тикете
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer(f"Тикет #{ticket_id} не найден")
        return
    
    user_id, status = row
    
    if status == 'closed':
        await message.answer(f"Тикет #{ticket_id} уже закрыт")
        return
    
    if close_ticket(ticket_id, message.from_user.id):
        await message.answer(f"✅ Тикет #{ticket_id} закрыт")
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"🔒 Ваше обращение #{ticket_id} было закрыто администратором.\n\n"
                f"Оцените качество поддержки:",
                reply_markup=get_rating_keyboard(ticket_id)
            )
        except:
            pass
    else:
        await message.answer(f"❌ Не удалось закрыть тикет #{ticket_id}")

@dp.message(Command("stats"))
async def stats_command(message: Message):
    """Команда /stats для просмотра статистики"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    stats = get_statistics()
    
    # Форматируем время ответа
    if stats['avg_response_seconds'] > 0:
        if stats['avg_response_seconds'] < 60:
            response_time = f"{stats['avg_response_seconds']} сек"
        elif stats['avg_response_seconds'] < 3600:
            response_time = f"{stats['avg_response_seconds'] // 60} мин"
        else:
            response_time = f"{stats['avg_response_seconds'] // 3600} ч"
    else:
        response_time = "нет данных"
    
    text = (
        f"📊 <b>СТАТИСТИКА ПОДДЕРЖКИ</b>\n\n"
        f"📋 <b>Тикеты:</b>\n"
        f"├ Всего: {stats['total_tickets']}\n"
        f"├ Открыто: {stats['open_tickets']}\n"
        f"└ Закрыто: {stats['closed_tickets']}\n\n"
        f"⭐️ <b>Оценки:</b>\n"
        f"├ Средняя: {stats['avg_rating']}/5\n"
        f"├ 5 ⭐️: {stats['rating_5']}\n"
        f"├ 4 ⭐️: {stats['rating_4']}\n"
        f"├ 3 ⭐️: {stats['rating_3']}\n"
        f"├ 2 ⭐️: {stats['rating_2']}\n"
        f"└ 1 ⭐️: {stats['rating_1']}\n\n"
        f"⏱ <b>Среднее время ответа:</b> {response_time}"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)

# --------------------- РЕГИСТРАЦИЯ АДМИНА ---------------------
@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    """Регистрация нового админа"""
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз или отправьте /cancel"
        )
        return
    
    save_admin_name(message.from_user.id, name)
    await state.clear()
    
    await message.answer(
        f"✅ Вы зарегистрированы как <b>{name}</b>\n\n"
        f"Теперь вы можете:\n"
        f"• Отвечать пользователям (reply на их сообщения)\n"
        f"• Использовать /admin_menu для управления\n"
        f"• Просматривать историю чатов",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_menu()
    )

# --------------------- ИЗМЕНЕНИЕ ИМЕНИ АДМИНА ---------------------
@dp.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext):
    """Изменение имени админа"""
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз:"
        )
        return
    
    save_admin_name(message.from_user.id, name)
    await state.clear()
    
    await message.answer(
        f"✅ Имя изменено на <b>{name}</b>",
        parse_mode=ParseMode.HTML
    )

# --------------------- ОБРАБОТКА CALLBACK ---------------------
@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка всех callback-запросов"""
    data = callback.data
    
    # Категории
    if data.startswith("category:"):
        category = data.split(":")[1]
        user = callback.from_user
        
        ticket_id = get_or_create_ticket(user, category)
        
        category_names = {
            'question': '❓ Вопрос',
            'problem': '⚠️ Проблема',
            'suggestion': '💡 Предложение',
            'other': '📌 Другое'
        }
        
        await callback.message.edit_text(
            f"<b>Категория:</b> {category_names.get(category, category)}\n"
            f"<b>Номер обращения:</b> #{ticket_id}\n\n"
            f"📝 Опишите вашу проблему или вопрос.\n"
            f"Можно отправлять текст, фото, видео, альбомы.",
            parse_mode=ParseMode.HTML
        )
        
        await state.set_state(TicketStates.in_dialog)
        await callback.answer()
        return
    
    # Оценка
    if data.startswith("rate:"):
        _, rating, ticket_id = data.split(":")
        rating = int(rating)
        ticket_id = int(ticket_id)
        
        save_rating(ticket_id, rating)
        
        await callback.message.edit_text(
            f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n"
            f"Если хотите оставить отзыв, напишите его сейчас.\n"
            f"Или отправьте /start для возврата в меню."
        )
        
        await state.set_state(TicketStates.waiting_feedback)
        await state.update_data(ticket_id=ticket_id, rating=rating)
        await callback.answer()
        return
    
    # Закрытие тикета
    if data.startswith("close:"):
        _, ticket_id, user_id = data.split(":")
        ticket_id = int(ticket_id)
        user_id = int(user_id)
        
        if close_ticket(ticket_id, callback.from_user.id):
            await callback.message.edit_text(f"✅ Тикет #{ticket_id} закрыт")
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"🔒 Ваше обращение #{ticket_id} было закрыто администратором.\n\n"
                    f"Оцените качество поддержки:",
                    reply_markup=get_rating_keyboard(ticket_id)
                )
            except:
                pass
        else:
            await callback.message.edit_text(f"❌ Тикет уже закрыт или не найден")
        
        await callback.answer()
        return
    
    # Поддержка
    if data == "support:start":
        await callback.message.edit_text(
            "Выберите категорию обращения:",
            reply_markup=get_category_menu()
        )
    
    elif data == "support:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Обращение отменено.",
            reply_markup=get_main_menu()
        )
    
    elif data == "support:continue":
        await state.set_state(TicketStates.in_dialog)
        await callback.message.edit_text(
            "📝 Продолжаем диалог. Напишите сообщение."
        )
    
    elif data == "menu:main":
        await state.clear()
        await callback.message.edit_text(
            "Главное меню:",
            reply_markup=get_main_menu()
        )
    
    elif data == "info:about":
        await callback.message.answer(
            "ℹ️ <b>Информация о поддержке</b>\n\n"
            "📌 <b>Правила:</b>\n"
            "• Не отправляйте пустые сообщения и стикеры\n"
            "• Описывайте проблему подробно\n"
            "• Будьте вежливы\n"
            "• Ожидайте ответа в рабочее время\n"
            "• Не спамьте (блокировка)\n\n"
            "⏱ <b>Время ответа:</b>\n"
            "Обычно в течение нескольких часов\n\n"
            "📞 <b>Связь:</b>\n"
            "Основной бот: @PulsOfficialManager_bot",
            parse_mode=ParseMode.HTML
        )
    
    # Админ-меню
    elif data == "admin:open_tickets":
        tickets = get_all_open_tickets()
        if not tickets:
            await callback.message.answer("📭 Нет открытых тикетов")
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for t in tickets[:10]:  # Показываем первые 10
            short_name = t[3][:15] + "..." if len(t[3]) > 15 else t[3]
            builder.button(
                text=f"#{t[0]} - {short_name} ({t[4]})", 
                callback_data=f"admin:view_ticket_{t[0]}"
            )
        
        if len(tickets) > 10:
            builder.button(text="📋 Все тикеты", callback_data="admin:all_tickets")
        
        builder.button(text="◀️ Назад", callback_data="admin:back")
        builder.adjust(1)
        
        await callback.message.answer(
            f"📂 <b>Открытые тикеты ({len(tickets)})</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    
    elif data == "admin:history":
        tickets = get_admin_tickets(callback.from_user.id)
        if not tickets:
            await callback.message.answer("📭 У вас нет истории чатов.")
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for t in tickets[:10]:
            status_emoji = "🟢" if t[3] == 'open' else "🔴"
            builder.button(
                text=f"{status_emoji} #{t[0]} - @{t[2] or 'без username'}", 
                callback_data=f"admin:view_ticket_{t[0]}"
            )
        
        if len(tickets) > 10:
            builder.button(text="📋 Вся история", callback_data="admin:all_history")
        
        builder.button(text="◀️ Назад", callback_data="admin:back")
        builder.adjust(1)
        
        await callback.message.answer(
            "📜 <b>Ваша история чатов</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    
    elif data.startswith("admin:view_ticket_"):
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id)
        
        # Получаем информацию о пользователе
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name, status FROM tickets WHERE id = ?", (ticket_id,))
        ticket_info = cursor.fetchone()
        conn.close()
        
        if not ticket_info:
            await callback.message.answer("❌ Тикет не найден")
            await callback.answer()
            return
        
        user_id, username, first_name, status = ticket_info
        status_emoji = "🟢" if status == 'open' else "🔴"
        
        text = f"<b>Тикет #{ticket_id}</b> {status_emoji}\n"
        text += f"👤 {first_name} (@{username or 'нет'})\n"
        text += f"🆔 <code>{user_id}</code>\n"
        text += "─" * 20 + "\n\n"
        
        if not messages:
            text += "📭 Нет сообщений"
        else:
            for msg in messages:
                sender_type, content, timestamp, media_group_id = msg
                time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
                sender = "👤 Пользователь" if sender_type == 'user' else "👨‍💼 Админ"
                media_mark = "📎 " if media_group_id else ""
                text += f"[{time_str}] {sender}: {media_mark}{content or '[медиа]'}\n\n"
        
        # Разбиваем длинное сообщение
        if len(text) > 4000:
            text = text[:4000] + "...\n\n(сообщение обрезано)"
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    elif data == "admin:profile":
        profile = get_admin_profile(callback.from_user.id)
        await callback.message.answer(profile, parse_mode=ParseMode.HTML)
    
    elif data == "admin:change_name":
        await callback.message.answer(
            "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminEditName.waiting_for_new_name)
    
    elif data == "admin:search":
        await callback.message.answer(
            "🔍 Введите текст для поиска по сообщениям\n"
            "Формат: /search <текст>"
        )
    
    elif data == "admin:stats":
        stats = get_statistics()
        
        if stats['avg_response_seconds'] > 0:
            if stats['avg_response_seconds'] < 60:
                response_time = f"{stats['avg_response_seconds']} сек"
            elif stats['avg_response_seconds'] < 3600:
                response_time = f"{stats['avg_response_seconds'] // 60} мин"
            else:
                response_time = f"{stats['avg_response_seconds'] // 3600} ч"
        else:
            response_time = "нет данных"
        
        text = (
            f"📊 <b>СТАТИСТИКА</b>\n\n"
            f"📋 Всего тикетов: {stats['total_tickets']}\n"
            f"├ Открыто: {stats['open_tickets']}\n"
            f"└ Закрыто: {stats['closed_tickets']}\n\n"
            f"⭐️ Средняя оценка: {stats['avg_rating']}/5\n"
            f"⏱ Среднее время ответа: {response_time}"
        )
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    elif data == "admin:delete_account":
        delete_admin_account(callback.from_user.id)
        await callback.message.answer(
            "🗑 Ваш аккаунт поддержки удалён.\n"
            "Для восстановления используйте /start"
        )
    
    elif data == "admin:back":
        await callback.message.edit_text(
            "🔧 <b>Меню поддержки</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_menu()
        )
    
    await callback.answer()

# --------------------- ПОИСК ---------------------
@dp.message(Command("search"))
async def search_command(message: Message):
    """Поиск по сообщениям"""
    if not is_admin(message.from_user.id):
        return
    
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("Введите текст для поиска")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.user_id, t.username, m.content, m.timestamp
        FROM messages m
        JOIN tickets t ON m.ticket_id = t.id
        WHERE m.content LIKE ? AND m.sender_type = 'user'
        ORDER BY m.timestamp DESC
        LIMIT 20
    """, (f"%{query}%",))
    
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        await message.answer("❌ Ничего не найдено")
        return
    
    builder = InlineKeyboardBuilder()
    for r in results:
        ticket_id, user_id, username, content, timestamp = r
        short_content = content[:30] + "..." if len(content) > 30 else content
        time_str = datetime.fromisoformat(timestamp).strftime("%d.%m")
        builder.button(
            text=f"#{ticket_id} @{username or 'no'} ({time_str}): {short_content}",
            callback_data=f"admin:view_ticket_{ticket_id}"
        )
    
    builder.adjust(1)
    await message.answer(f"🔍 Результаты поиска по '{query}':", reply_markup=builder.as_markup())

# --------------------- ОБРАБОТКА СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЯ ---------------------
@dp.message(TicketStates.in_dialog, F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    """Обработка сообщений от пользователя в диалоге"""
    user = message.from_user
    
    # Проверка на спам-блок
    blocked, block_msg = check_spam_block(user.id)
    if blocked:
        await message.answer(block_msg)
        return
    
    # Проверка кулдауна
    cooldown, cooldown_msg = check_message_cooldown(user.id)
    if cooldown:
        await message.answer(cooldown_msg)
        return
    
    # Проверка лимита сообщений без ответа
    limit_exceeded, limit_msg = check_message_limit(user.id)
    if limit_exceeded:
        await message.answer(limit_msg)
        return
    
    ticket_status = get_ticket_status(user.id)
    if ticket_status:
        status, has_responded = ticket_status
        if status == 'open' and has_responded == 0:
            # Первое сообщение уже отправлено и ждёт ответа
            await message.answer(
                "⏳ Дождитесь ответа поддержки прежде чем отправить новое сообщение.\n"
                "Спам может привести к блокировке."
            )
            return
    
    # Фильтр спама (эмодзи, стикеры и т.д.)
    if message.sticker or message.animation or message.dice:
        await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
        return
    
    if message.text and len(message.text.strip()) < 3 and not any(c.isalpha() for c in message.text):
        await message.answer("❌ Слишком короткое сообщение. Опишите проблему подробнее.")
        return
    
    # Получаем или создаем тикет
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category FROM tickets WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    
    if row:
        ticket_id, category = row
    else:
        # Если нет тикета, просим выбрать категорию
        await state.clear()
        await message.answer(
            "Пожалуйста, сначала выберите категорию обращения:",
            reply_markup=get_category_menu()
        )
        conn.close()
        return
    
    conn.close()
    
    # Обработка альбомов
    if message.media_group_id:
        media_groups_buffer[message.media_group_id].append(message)
        
        # Ждем немного, чтобы собрать все сообщения альбома
        await asyncio.sleep(1)
        
        # Проверяем, собрали ли все сообщения
        if message.media_group_id in media_groups_buffer:
            messages = media_groups_buffer.pop(message.media_group_id)
            
            # Сохраняем альбом в БД
            for msg in messages:
                file_id = None
                media_type = None
                
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    media_type = 'photo'
                elif msg.video:
                    file_id = msg.video.file_id
                    media_type = 'video'
                
                if file_id:
                    save_media_group(
                        message.media_group_id,
                        ticket_id,
                        msg.message_id,
                        file_id,
                        media_type,
                        msg.caption
                    )
            
            # Сохраняем запись о сообщении
            save_message(ticket_id, 'user', user.id, f"[Альбом] {messages[0].caption or ''}", message.media_group_id)
            
            # Пересылаем админам
            user_info = (
                f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
                f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
                f"ID: <code>{user.id}</code>\n"
                f"@{user.username or 'нет'}\n"
                f"──────────────────────\n"
                f"<b>Альбом ({len(messages)} шт.)</b>\n"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
                    
                    # Отправляем альбом
                    media_group = []
                    for msg in messages:
                        if msg.photo:
                            media_group.append(types.InputMediaPhoto(
                                media=msg.photo[-1].file_id,
                                caption=msg.caption if msg == messages[0] else None
                            ))
                        elif msg.video:
                            media_group.append(types.InputMediaVideo(
                                media=msg.video.file_id,
                                caption=msg.caption if msg == messages[0] else None
                            ))
                    
                    await bot.send_media_group(admin_id, media_group)
                except Exception as e:
                    logging.error(f"Ошибка отправки админу {admin_id}: {e}")
            
            await message.answer(
                f"✅ Альбом отправлен в тикет #{ticket_id}.",
                reply_markup=get_after_message_menu()
            )
            
            update_message_time(user.id)
            return
    
    # Обычное сообщение
    content = message.text or "[Медиа]"
    
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text)
    elif message.photo:
        file_id = message.photo[-1].file_id
        save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}")
        save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, file_id, 'photo', message.caption)
    elif message.video:
        file_id = message.video.file_id
        save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}")
        save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, file_id, 'video', message.caption)
    elif message.voice:
        save_message(ticket_id, 'user', user.id, "[Голосовое сообщение]")
    elif message.document:
        save_message(ticket_id, 'user', user.id, f"[Документ] {message.document.file_name}")
    
    # Отправка админам
    user_info = (
        f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
        f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"ID: <code>{user.id}</code>\n"
        f"@{user.username or 'нет'}\n"
        f"──────────────────────\n"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            
            if message.text:
                await bot.send_message(admin_id, message.text)
            elif message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(admin_id, message.video.file_id, caption=message.caption)
            elif message.voice:
                await bot.send_voice(admin_id, message.voice.file_id)
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=message.caption)
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    await message.answer(
        f"✅ Сообщение отправлено в тикет #{ticket_id}.",
        reply_markup=get_after_message_menu()
    )
    
    update_message_time(user.id)
    
    # Если это первое сообщение, обновляем статус
    if ticket_status and ticket_status[1] == 1:
        reset_has_responded(user.id)

# --------------------- ОБРАБОТКА ОТЗЫВА ---------------------
@dp.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    """Обработка текстового отзыва после оценки"""
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    rating = data.get('rating')
    
    if message.text:
        save_rating(ticket_id, rating, message.text)
        await message.answer(
            "✅ Спасибо за ваш отзыв!\n"
            "Он поможет нам стать лучше."
        )
    else:
        await message.answer("Отзыв сохранен без комментария.")
    
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_menu())

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None)
async def handle_admin_reply(message: Message):
    """Обработка ответа админа (reply на сообщение пользователя)"""
    replied = message.reply_to_message
    
    # Определяем ID пользователя
    user_id = None
    
    if replied.from_user.id == bot.id and replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.text and "ID: <code>" in replied.text:
        # Парсим ID из сообщения админу
        match = re.search(r'ID: <code>(\d+)</code>', replied.text)
        if match:
            user_id = int(match.group(1))
    
    if not user_id:
        await message.reply("❌ Не удалось определить пользователя. Ответьте на пересланное сообщение.")
        return
    
    admin_name = get_admin_name(message.from_user.id)
    
    if not admin_name:
        await message.reply(
            "❌ Вы не зарегистрированы в системе поддержки.\n"
            "Используйте /start для регистрации."
        )
        return
    
    update_admin_activity(message.from_user.id)
    
    # Получаем номер тикета
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tickets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await message.reply("❌ Тикет не найден")
        conn.close()
        return
    
    ticket_id = row[0]
    conn.close()
    
    try:
        prefix = f"✉️ <b>Ответ от {admin_name}</b>\n\n"
        
        if message.text:
            await bot.send_message(user_id, prefix + message.text, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, message.text)
        elif message.photo:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_photo(user_id, message.photo[-1].file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Фото] {message.caption or ''}")
        elif message.video:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_video(user_id, message.video.file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Видео] {message.caption or ''}")
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
            await bot.send_message(user_id, prefix + "↑", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, "[Голосовое сообщение]")
        elif message.document:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_document(user_id, message.document.file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Документ] {message.document.file_name}")
        else:
            await message.reply("❌ Неподдерживаемый тип сообщения")
            return
        
        update_has_responded(user_id)
        
        await message.reply(
            f"✅ Ответ отправлен от имени {admin_name}",
            reply_markup=get_ticket_actions_keyboard(ticket_id, user_id)
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при отправке: {e}")
        logging.error(f"Ошибка ответа админа: {e}")

# --------------------- ОБРАБОТКА МЕДИА ГРУПП ОТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.media_group_id)
async def handle_admin_media_group(message: Message):
    """Обработка альбомов от админа"""
    if not message.reply_to_message:
        return
    
    # Здесь аналогичная логика сбора альбома, но для простоты 
    # предлагаем админу отправлять фото/видео по одному или использовать /reply
    await message.reply(
        "⚠️ Для отправки альбома используйте команду /reply с номером тикета\n"
        "Или отправляйте фото/видео по одному"
    )

# --------------------- ПЛАНИРОВЩИК ЗАДАЧ ---------------------
async def scheduler():
    """Планировщик для периодических задач"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            closed = auto_close_old_tickets()
            if closed > 0:
                logging.info(f"Авто-закрыто {closed} тикетов")
        except Exception as e:
            logging.error(f"Ошибка в планировщике: {e}")

# --------------------- ЗАПУСК ---------------------
async def main():
    """Основная функция запуска бота"""
    logging.info("Бот поддержки запущен")
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
