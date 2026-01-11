#!/usr/bin/env python3
"""
🎖️ Телеграм бот с полной системой рангов, наказаний, триггеров и приветствием с кнопками
"""

import asyncio
import logging
import sqlite3
import random
import re
import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, CallbackQuery, ReplyKeyboardRemove
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.exceptions import TelegramUnauthorizedError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8566099089:AAGC-BwcC2mia46iG-aNL9_931h5xV21b9c"
ADMIN_IDS = [6708209142]  # ID создателя
BOT_OWNER_USERNAME = "@vanezyyy"  # Юзернейм создателя
DEFAULT_MAX_WARNINGS = 5
RULES_CHANNEL = "https://t.me/RulesPulsOfficial"

RANKS = {
    0: "👤 Участник",
    1: "👮 Младший модератор", 
    2: "🛡️ Старший модератор",
    3: "👑 Администратор",
    4: "🌟 Продвинутый админ",
    5: "✨ СОЗДАТЕЛЬ"
}

# ===================== STATES ДЛЯ FSM =====================
class GroupSettingsStates(StatesGroup):
    waiting_for_group_link = State()
    waiting_for_punishment_type = State()
    waiting_for_punishment_time = State()
    waiting_for_edit_punishment = State()
    waiting_for_edit_time = State()
    waiting_for_rules_text = State()

class AdminPanelStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_note_title = State()
    waiting_for_note_content = State()
    waiting_for_beta_tester_username = State()
    waiting_for_beta_tester_new_username = State()

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        logger.info("База данных подключена")

    def create_tables(self):
        cur = self.conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            first_name TEXT,
            rank INTEGER DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            mutes INTEGER DEFAULT 0,
            bans INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_command_time TIMESTAMP,
            is_beta_tester INTEGER DEFAULT 0,
            user_role TEXT DEFAULT 'участник',
            PRIMARY KEY (user_id, chat_id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS rules (
            chat_id INTEGER PRIMARY KEY,
            text TEXT
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS punishments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            type TEXT,
            moderator_id INTEGER,
            moderator_username TEXT,
            reason TEXT,
            end_time TIMESTAMP,
            message_id INTEGER,
            active INTEGER DEFAULT 1
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS chat_owners (
            chat_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS group_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            max_warnings INTEGER DEFAULT 5,
            punishment_type TEXT DEFAULT 'м',
            punishment_time TEXT DEFAULT '1д',
            group_username TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS user_cooldowns (
            user_id INTEGER,
            chat_id INTEGER,
            command TEXT,
            last_used TIMESTAMP,
            PRIMARY KEY (user_id, chat_id, command)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS admin_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            title TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS beta_testers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by INTEGER
        )''')
        self.conn.commit()

    def add_user(self, user_id: int, chat_id: int, username: str, first_name: str):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR IGNORE INTO users 
                      (user_id, chat_id, username, first_name) 
                      VALUES (?, ?, ?, ?)''',
                   (user_id, chat_id, username, first_name))
        self.conn.commit()

    def update_message_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET message_count = message_count + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def get_user(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        return cur.fetchone()

    def get_user_global(self, user_id: int):
        """Получает глобальную информацию о пользователе"""
        cur = self.conn.cursor()
        # Получаем информацию из admins
        cur.execute('''SELECT * FROM admins WHERE user_id=?''', (user_id,))
        admin_data = cur.fetchone()
        
        # Получаем информацию из beta_testers
        cur.execute('''SELECT * FROM beta_testers WHERE user_id=?''', (user_id,))
        beta_tester_data = cur.fetchone()
        
        result = {
            'is_admin': admin_data is not None,
            'is_beta_tester': beta_tester_data is not None
        }
        
        if admin_data:
            result['admin_data'] = dict(admin_data)
        
        if beta_tester_data:
            result['beta_tester_data'] = dict(beta_tester_data)
            
        return result

    def set_rank(self, user_id: int, chat_id: int, rank: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET rank=? WHERE user_id=? AND chat_id=?''',
                   (rank, user_id, chat_id))
        self.conn.commit()

    def add_warning(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET warnings = warnings + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()
        cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        result = cur.fetchone()
        return result['warnings'] if result else 0

    def get_warnings(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        result = cur.fetchone()
        return result['warnings'] if result else 0

    def reset_warnings(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET warnings=0 WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_mute_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET mutes = mutes + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_ban_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET bans = bans + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def set_rules(self, chat_id: int, text: str):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO rules (chat_id, text) 
                      VALUES (?, ?)''',
                   (chat_id, text))
        self.conn.commit()

    def get_rules(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT text FROM rules WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        return result['text'] if result else "Правила ещё не установлены. Используй команду 'п текст'"

    def add_punishment(self, chat_id: int, user_id: int, punishment_type: str, 
                      moderator_id: int, moderator_username: str, reason: str, 
                      end_time: datetime, message_id: int = None):
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO punishments 
                      (chat_id, user_id, type, moderator_id, moderator_username, reason, end_time, message_id) 
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                   (chat_id, user_id, punishment_type, moderator_id, moderator_username, 
                    reason, end_time.isoformat(), message_id))
        self.conn.commit()
        return cur.lastrowid

    def get_active_punishments(self, chat_id: int, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments 
                      WHERE chat_id=? AND user_id=? AND active=1 
                      ORDER BY end_time DESC''',
                   (chat_id, user_id))
        return cur.fetchall()

    def get_punishment_by_id(self, punishment_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments WHERE id=?''', (punishment_id,))
        return cur.fetchone()

    def remove_punishment(self, punishment_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE punishments SET active=0 WHERE id=?''', (punishment_id,))
        self.conn.commit()

    def get_expired_punishments(self):
        cur = self.conn.cursor()
        current_time = datetime.now().isoformat()
        cur.execute('''SELECT * FROM punishments 
                      WHERE active=1 AND end_time < ?''',
                   (current_time,))
        return cur.fetchall()

    def get_all_users_in_chat(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE chat_id=? ORDER BY rank DESC, message_count DESC''', 
                   (chat_id,))
        return cur.fetchall()

    def set_chat_owner(self, chat_id: int, owner_id: int):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO chat_owners (chat_id, owner_id) 
                      VALUES (?, ?)''',
                   (chat_id, owner_id))
        self.conn.commit()

    def get_chat_owner(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT owner_id FROM chat_owners WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        return result['owner_id'] if result else None

    def get_group_settings(self, chat_id: int = None, user_id: int = None):
        cur = self.conn.cursor()
        if chat_id:
            cur.execute('''SELECT * FROM group_settings WHERE chat_id=?''', (chat_id,))
            result = cur.fetchone()
            if result:
                return dict(result)
        elif user_id:
            cur.execute('''SELECT * FROM group_settings WHERE user_id=? ORDER BY created_at DESC''', (user_id,))
            result = cur.fetchall()
            return [dict(row) for row in result]
        return None

    def add_group_setting(self, chat_id: int, user_id: int, group_username: str = None):
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO group_settings 
                      (chat_id, user_id, group_username) 
                      VALUES (?, ?, ?)''',
                   (chat_id, user_id, group_username))
        self.conn.commit()
        return cur.lastrowid

    def update_group_settings(self, chat_id: int, max_warnings: int = None, 
                            punishment_type: str = None, punishment_time: str = None):
        cur = self.conn.cursor()
        
        # Проверяем существующие настройки
        cur.execute('''SELECT * FROM group_settings WHERE chat_id=?''', (chat_id,))
        existing = cur.fetchone()
        
        if existing:
            # Обновляем существующие
            updates = []
            params = []
            
            if max_warnings is not None:
                updates.append("max_warnings=?")
                params.append(max_warnings)
            
            if punishment_type is not None:
                updates.append("punishment_type=?")
                params.append(punishment_type)
            
            if punishment_time is not None:
                updates.append("punishment_time=?")
                params.append(punishment_time)
            
            if updates:
                query = f"UPDATE group_settings SET {', '.join(updates)} WHERE chat_id=?"
                params.append(chat_id)
                cur.execute(query, params)
        else:
            # Создаем новые
            cur.execute('''INSERT INTO group_settings 
                          (chat_id, max_warnings, punishment_type, punishment_time) 
                          VALUES (?, ?, ?, ?)''',
                       (chat_id, 
                        max_warnings if max_warnings is not None else DEFAULT_MAX_WARNINGS,
                        punishment_type if punishment_type is not None else 'м',
                        punishment_time if punishment_time is not None else '1д'))
        
        self.conn.commit()
        return True

    def get_max_warnings_for_chat(self, chat_id: int):
        settings = self.get_group_settings(chat_id)
        if settings and 'max_warnings' in settings:
            return settings['max_warnings']
        return DEFAULT_MAX_WARNINGS

    def check_cooldown(self, user_id: int, chat_id: int, command: str, cooldown_seconds: int = 10):
        cur = self.conn.cursor()
        cur.execute('''SELECT last_used FROM user_cooldowns 
                      WHERE user_id=? AND chat_id=? AND command=?''',
                   (user_id, chat_id, command))
        result = cur.fetchone()
        
        if not result:
            # Записываем текущее время
            cur.execute('''INSERT OR REPLACE INTO user_cooldowns 
                          (user_id, chat_id, command, last_used) 
                          VALUES (?, ?, ?, ?)''',
                       (user_id, chat_id, command, datetime.now().isoformat()))
            self.conn.commit()
            return True
        
        last_used = datetime.fromisoformat(result['last_used'])
        now = datetime.now()
        time_diff = (now - last_used).total_seconds()
        
        if time_diff >= cooldown_seconds:
            # Обновляем время
            cur.execute('''UPDATE user_cooldowns SET last_used=? 
                          WHERE user_id=? AND chat_id=? AND command=?''',
                       (now.isoformat(), user_id, chat_id, command))
            self.conn.commit()
            return True
        
        return False

    def get_all_group_settings(self):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM group_settings''')
        return cur.fetchall()

    # ===================== АДМИН ФУНКЦИИ =====================
    
    def add_admin(self, user_id: int, username: str, first_name: str, added_by: int):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO admins (user_id, username, first_name, added_by) 
                      VALUES (?, ?, ?, ?)''',
                   (user_id, username, first_name, added_by))
        self.conn.commit()
        return True

    def remove_admin(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''DELETE FROM admins WHERE user_id=?''', (user_id,))
        self.conn.commit()
        return True

    def get_admin(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM admins WHERE user_id=?''', (user_id,))
        result = cur.fetchone()
        return dict(result) if result else None

    def get_all_admins(self):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM admins ORDER BY added_at DESC''')
        return [dict(row) for row in cur.fetchall()]

    def is_admin(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT 1 FROM admins WHERE user_id=?''', (user_id,))
        return cur.fetchone() is not None

    # ===================== АДМИНСКИЕ ЗАМЕТКИ =====================
    
    def add_admin_note(self, admin_id: int, title: str, content: str):
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO admin_notes (admin_id, title, content) 
                      VALUES (?, ?, ?)''',
                   (admin_id, title, content))
        self.conn.commit()
        return cur.lastrowid

    def get_admin_notes(self, admin_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM admin_notes WHERE admin_id=? ORDER BY created_at DESC''', 
                   (admin_id,))
        return [dict(row) for row in cur.fetchall()]

    def get_admin_note(self, note_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM admin_notes WHERE id=?''', (note_id,))
        result = cur.fetchone()
        return dict(result) if result else None

    def delete_admin_note(self, note_id: int):
        cur = self.conn.cursor()
        cur.execute('''DELETE FROM admin_notes WHERE id=?''', (note_id,))
        self.conn.commit()
        return True

    # ===================== БЕТА ТЕСТЕРЫ =====================
    
    def add_beta_tester(self, user_id: int, username: str, first_name: str, added_by: int):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO beta_testers (user_id, username, first_name, added_by) 
                      VALUES (?, ?, ?, ?)''',
                   (user_id, username, first_name, added_by))
        
        # Обновляем статус в таблице users для всех чатов
        cur.execute('''UPDATE users SET is_beta_tester=1 WHERE user_id=?''', (user_id,))
        self.conn.commit()
        return True

    def remove_beta_tester(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''DELETE FROM beta_testers WHERE user_id=?''', (user_id,))
        
        # Обновляем статус в таблице users для всех чатов
        cur.execute('''UPDATE users SET is_beta_tester=0 WHERE user_id=?''', (user_id,))
        self.conn.commit()
        return True

    def update_beta_tester_username(self, user_id: int, new_username: str):
        cur = self.conn.cursor()
        cur.execute('''UPDATE beta_testers SET username=? WHERE user_id=?''', 
                   (new_username, user_id))
        
        # Обновляем username в таблице users для всех чатов
        cur.execute('''UPDATE users SET username=? WHERE user_id=?''', (new_username, user_id))
        self.conn.commit()
        return True

    def get_beta_tester(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM beta_testers WHERE user_id=?''', (user_id,))
        result = cur.fetchone()
        return dict(result) if result else None

    def get_all_beta_testers(self):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM beta_testers ORDER BY added_at DESC''')
        return [dict(row) for row in cur.fetchall()]

    def is_beta_tester(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT 1 FROM beta_testers WHERE user_id=?''', (user_id,))
        return cur.fetchone() is not None

# ===================== КЛАСС БОТА =====================
class BotCore:
    def __init__(self):
        storage = MemoryStorage()
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher(storage=storage)
        self.router = Router()
        self.db = Database()
        self.dp.include_router(self.router)
        self.bot_info = None

    async def check_bot_token(self):
        try:
            self.bot_info = await self.bot.get_me()
            logger.info(f"Бот успешно запущен: @{self.bot_info.username}")
            return True
        except TelegramUnauthorizedError:
            logger.error("Неверный токен бота!")
            return False

    async def check_user_permissions(self, chat_id: int, user_id: int):
        try:
            chat_member = await self.bot.get_chat_member(chat_id, user_id)
            is_admin = chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            is_creator = chat_member.status == ChatMemberStatus.CREATOR
            return is_admin, is_creator
        except Exception as e:
            logger.error(f"Ошибка проверки прав: {e}")
            return False, False

    async def check_expired_punishments(self):
        """Периодически проверяет истекшие наказания"""
        while True:
            try:
                expired = self.db.get_expired_punishments()
                for punishment in expired:
                    try:
                        punishment_id = punishment['id']
                        chat_id = punishment['chat_id']
                        user_id = punishment['user_id']
                        punishment_type = punishment['type']
                        
                        # Обновляем статус наказания
                        self.db.remove_punishment(punishment_id)
                        
                        # Для мутов восстанавливаем права
                        if punishment_type in ['мут', 'м']:
                            try:
                                # Восстанавливаем права пользователя
                                permissions = ChatPermissions(
                                    can_send_messages=True,
                                    can_send_media_messages=True,
                                    can_send_polls=True,
                                    can_send_other_messages=True,
                                    can_add_web_page_previews=True,
                                    can_change_info=False,
                                    can_invite_users=True,
                                    can_pin_messages=False
                                )
                                await self.bot.restrict_chat_member(
                                    chat_id=chat_id,
                                    user_id=user_id,
                                    permissions=permissions
                                )
                                logger.info(f"Снят мут для пользователя {user_id} в чате {chat_id}")
                            except Exception as e:
                                logger.error(f"Ошибка при снятии мута: {e}")
                        
                        logger.info(f"Наказание {punishment_id} истекло и удалено")
                        
                    except Exception as e:
                        logger.error(f"Ошибка обработки истекшего наказания: {e}")
                
                # Проверяем каждые 60 секунд
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в check_expired_punishments: {e}")
                await asyncio.sleep(60)

    async def parse_time_string(self, time_str: str) -> Optional[timedelta]:
        """Парсит строку времени типа '30м', '2ч', '1д' и т.д."""
        try:
            time_str = time_str.strip().lower()
            
            if time_str.endswith('м'):
                minutes = int(time_str[:-1])
                return timedelta(minutes=minutes)
            elif time_str.endswith('ч'):
                hours = int(time_str[:-1])
                return timedelta(hours=hours)
            elif time_str.endswith('д'):
                days = int(time_str[:-1])
                return timedelta(days=days)
            elif time_str.endswith('н'):
                weeks = int(time_str[:-1])
                return timedelta(weeks=weeks)
            elif time_str.endswith('с'):
                seconds = int(time_str[:-1])
                return timedelta(seconds=seconds)
            else:
                # Пробуем распознать как число минут
                try:
                    minutes = int(time_str)
                    return timedelta(minutes=minutes)
                except:
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка парсинга времени: {e}")
            return None

    def format_time_string(self, time_delta: timedelta) -> str:
        """Форматирует timedelta в строку времени"""
        total_seconds = time_delta.total_seconds()
        
        if total_seconds >= 604800:  # 1 неделя
            weeks = int(total_seconds // 604800)
            return f"{weeks}н"
        elif total_seconds >= 86400:  # 1 день
            days = int(total_seconds // 86400)
            return f"{days}д"
        elif total_seconds >= 3600:  # 1 час
            hours = int(total_seconds // 3600)
            return f"{hours}ч"
        elif total_seconds >= 60:  # 1 минута
            minutes = int(total_seconds // 60)
            return f"{minutes}м"
        else:
            seconds = int(total_seconds)
            return f"{seconds}с"

    async def apply_punishment(self, chat_id: int, user_id: int, punishment_type: str, 
                              time_str: str, reason: str, moderator_id: int, moderator_username: str):
        """Применяет наказание к пользователю"""
        try:
            # Парсим время
            time_delta = await self.parse_time_string(time_str)
            if not time_delta:
                return False, "Неверный формат времени. Используй: 30м, 2ч, 1д и т.д."
            
            end_time = datetime.now() + time_delta
            
            # Применяем наказание в зависимости от типа
            if punishment_type in ['мут', 'м']:
                permissions = ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                )
                await self.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                    until_date=int(end_time.timestamp())
                )
                self.db.add_mute_count(user_id, chat_id)
                punishment_desc = f"🔇 Мут на {time_str}"
                
            elif punishment_type in ['бан', 'б']:
                await self.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    until_date=int(end_time.timestamp())
                )
                self.db.add_ban_count(user_id, chat_id)
                punishment_desc = f"🚫 Бан на {time_str}"
                
            elif punishment_type in ['кик', 'к']:
                await self.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    until_date=int((datetime.now() + timedelta(minutes=5)).timestamp())
                )
                punishment_desc = "👢 Кик"
                end_time = datetime.now()  # Для кика время не имеет значения
                
            elif punishment_type in ['варн', 'в']:
                # Для варна просто добавляем предупреждение
                warnings = self.db.add_warning(user_id, chat_id)
                max_warnings = DEFAULT_MAX_WARNINGS
                
                punishment_desc = f"⚠️ Предупреждение ({warnings}/{max_warnings})"
                end_time = datetime.now()  # Предупреждения не имеют срока
                
                # Проверяем, не превышен ли лимит предупреждений
                if warnings >= max_warnings:
                    # Применяем наказание из настроек группы
                    settings = self.db.get_group_settings(chat_id)
                    if settings:
                        auto_punishment = settings.get('punishment_type', 'м')
                        auto_time = settings.get('punishment_time', '1д')
                        
                        # Сбрасываем предупреждения
                        self.db.reset_warnings(user_id, chat_id)
                        
                        # Применяем автоматическое наказание
                        await self.apply_punishment(
                            chat_id, user_id, auto_punishment, 
                            auto_time, f"Автонаказание за {max_warnings} предупреждений", 
                            moderator_id, moderator_username
                        )
                        
                        return True, f"Достигнут лимит предупреждений! Автоматически применено наказание: {auto_punishment} на {auto_time}"
                
            else:
                return False, f"Неизвестный тип наказания: {punishment_type}"
            
            # Сохраняем наказание в базу с юзернеймом модератора
            punishment_id = self.db.add_punishment(
                chat_id, user_id, punishment_type, 
                moderator_id, moderator_username, reason, end_time
            )
            
            # Создаем сообщение с кнопкой снятия наказания
            try:
                target_user = await self.bot.get_chat(user_id)
                target_name = f"@{target_user.username}" if target_user.username else target_user.first_name
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔓 Снять наказание", callback_data=f"remove_punish_{punishment_id}")]
                    ]
                )
                
                message_text = f"""{punishment_desc}
👤 Нарушитель: {target_name}
🔨 Модератор: @{moderator_username}
📝 Причина: {reason}"""
                
                sent_message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    reply_markup=kb
                )
                
                # Обновляем наказание с ID сообщения
                cur = self.db.conn.cursor()
                cur.execute('''UPDATE punishments SET message_id=? WHERE id=?''', 
                          (sent_message.message_id, punishment_id))
                self.db.conn.commit()
                
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения о наказании: {e}")
            
            return True, f"{punishment_desc}\nПричина: {reason}\n👤 Нарушитель: {target_name if 'target_name' in locals() else user_id}"
            
        except Exception as e:
            logger.error(f"Ошибка применения наказания: {e}")
            return False, f"Ошибка: {str(e)}"

    async def handle_command_without_slash(self, message: Message):
        """Обработка команд без слеша"""
        text = message.text.strip()
        
        # Проверяем, является ли это командой модерации (первая буква - команда)
        if len(text) > 0 and text[0].lower() in ['м', 'б', 'к', 'в', 'п']:
            await self.handle_moderation_command(message, text[0].lower(), text)
            return
            
        # Другие команды без слеша
        text_lower = text.lower()
        
        if text_lower == 'помощь':
            await self.handle_help(message)
            return
        elif text_lower == 'правила':
            await self.handle_rules(message)
            return
        elif text_lower == 'профиль' or text_lower == 'проф':
            await self.handle_profile(message)
            return
        elif text_lower == 'ранги':
            await self.handle_ranks(message)
            return
        elif text_lower == 'стата':
            await self.handle_stats(message)
            return
        elif text_lower == 'пульс':
            await self.handle_pulse(message)
            return
        elif text_lower == 'обновить пульс':
            await self.handle_update_pulse(message)
            return

    async def handle_moderation_command(self, message: Message, command: str, text: str):
        """Обработка команд модерации"""
        try:
            # Проверяем права пользователя
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 1:
                await message.reply("❌ У тебя нет прав на модерацию.\nНужен ранг 1 или выше.")
                return
            
            # Определяем цель наказания
            target = None
            time_str = None
            reason = "Без причины"
            
            # Обработка ответа на сообщение
            if message.reply_to_message:
                target = message.reply_to_message.from_user.id
                moderator_username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                
                # Извлекаем причину и время из текста
                parts = text.split()
                if len(parts) > 1:
                    # Команда мут: м 30м причина
                    if command == 'м':
                        if len(parts) >= 3:
                            time_str = parts[1]
                            reason = ' '.join(parts[2:]) if len(parts) > 2 else "Без причины"
                        else:
                            await message.reply("❌ Для мута нужно указать время.\nПример: `м 30м причина` или ответом на сообщение: `м 30м`")
                            return
                    else:
                        # Для других команд просто причина
                        if len(parts) > 1:
                            reason = ' '.join(parts[1:])
                
                if command == 'м' and not time_str:
                    time_str = '30м'  # По умолчанию 30 минут
                    
            else:
                # Обработка команды с упоминанием или ID
                parts = text.split()
                if len(parts) < 2:
                    await message.reply(f"❌ Не указан пользователь.\nПример: `{command} @username причина` или ответом на сообщение")
                    return
                
                # Пытаемся определить цель
                target_str = parts[1]
                target = await self.parse_user_mention(target_str, message.chat.id)
                
                if not target:
                    await message.reply("❌ Не удалось найти пользователя. Укажите @username, ID или ответьте на сообщение.")
                    return
                
                moderator_username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                
                # Извлекаем время и причину
                if command == 'м':
                    if len(parts) >= 3:
                        time_str = parts[2]
                        reason = ' '.join(parts[3:]) if len(parts) > 3 else "Без причины"
                    else:
                        await message.reply("❌ Для мута нужно указать время.\nПример: `м @username 30м причина`")
                        return
                else:
                    reason = ' '.join(parts[2:]) if len(parts) > 2 else "Без причины"
            
            if command == 'м' and not time_str:
                time_str = '30м'
            elif command != 'м':
                time_str = '1д'  # Для бана/кика по умолчанию
            
            # Преобразуем команду в полное название
            punishment_type = {
                'м': 'мут',
                'б': 'бан',
                'к': 'кик',
                'в': 'варн',
                'п': 'правила'
            }.get(command, command)
            
            # Если это команда установки правил
            if command == 'п':
                if user_data['rank'] < 5:
                    await message.reply("❌ Устанавливать правила может только создатель чата.")
                    return
                
                if len(parts) > 1:
                    rules_text = ' '.join(parts[1:])
                    self.db.set_rules(message.chat.id, rules_text)
                    await message.reply(f"✅ Правила установлены!\n\n{rules_text}")
                else:
                    await message.reply("❌ Укажите текст правил.\nПример: `п 1. Не спамить\n2. Не оскорблять`")
                return
            
            # Проверяем, можно ли наказать этого пользователя
            target_data = self.db.get_user(target, message.chat.id)
            if target_data and target_data['rank'] >= user_data['rank']:
                await message.reply("❌ Нельзя наказать пользователя с равным или высшим рангом.")
                return
            
            # Применяем наказание
            success, result_msg = await self.apply_punishment(
                message.chat.id, target, punishment_type,
                time_str, reason, message.from_user.id, moderator_username
            )
            
            if success:
                # Удаляем сообщение пользователя если нужно
                try:
                    await message.delete()
                except:
                    pass
            else:
                await message.reply(f"❌ {result_msg}")
                
        except Exception as e:
            logger.error(f"Ошибка обработки команды модерации: {e}")
            await message.reply("❌ Ошибка обработки команды.")

    async def parse_user_mention(self, mention: str, chat_id: int) -> Optional[int]:
        """Парсит упоминание пользователя"""
        try:
            # Если это ID
            if mention.isdigit():
                return int(mention)
            
            # Если это упоминание вида @username
            if mention.startswith('@'):
                # В реальном боте нужно искать по участникам чата
                # Для простоты возвращаем None - будет обрабатываться через ответ на сообщение
                return None
            
            return None
        except:
            return None

    async def handle_pulse(self, message: Message):
        """Обработка команды пульс"""
        try:
            # Проверяем кд для пользователей 0 ранга
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            
            if user_data and user_data['rank'] == 0:
                if not self.db.check_cooldown(message.from_user.id, message.chat.id, "пульс", 10):
                    await message.reply("⏳ Подождите 10 секунд перед использованием этой команды снова.")
                    return
            
            responses = [
                "⚡ Пульс активен! Система готова к работе!",
                "💓 Бот жив и работает стабильно!",
                "🌀 Энергия течет, системы в норме!",
                "🔋 Заряд 100%! Все функции доступны!",
                "⚙️ Все системы функционируют в оптимальном режиме!",
                "💫 Связь установлена! Бот на связи!",
                "🌐 Сеть стабильна! Все модули активны!",
                "🚀 Производительность на максимуме! Готов к работе!",
                "🛡️ Защитные системы активированы! Бот под охраной!",
                "🎯 Точность 99.9%! Все команды обрабатываются мгновенно!",
            ]
            
            await message.reply(random.choice(responses))
            
        except Exception as e:
            logger.error(f"Ошибка обработки пульс: {e}")

    async def handle_update_pulse(self, message: Message):
        """Обработка команды обновить пульс"""
        try:
            # Проверяем права для этой команды
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 1:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 1 или выше.")
                return
            
            # Проверяем кд для пользователей 1 ранга
            if user_data['rank'] == 1:
                if not self.db.check_cooldown(message.from_user.id, message.chat.id, "обновить пульс", 10):
                    await message.reply("⏳ Подождите 10 секунд перед использованием этой команды снова.")
                    return
            
            msg = await message.reply("🔄 Обновляю все изменения и бота...")
            await asyncio.sleep(0.8)
            
            # Обновляем настройки группы
            settings = self.db.get_group_settings(message.chat.id)
            if settings:
                max_warnings = settings.get('max_warnings', DEFAULT_MAX_WARNINGS)
                await msg.edit_text(f"✅ Все функции применены, бот работает нормально\n"
                                   f"⚙️ Настройки группы обновлены (макс. варнов: {max_warnings})")
            else:
                await msg.edit_text("✅ Все функции применены, бот работает нормально")
                
        except Exception as e:
            logger.error(f"Ошибка обработки обновить пульс: {e}")

    async def handle_start(self, message: Message):
        """Обработка /start"""
        try:
            # Добавляем пользователя в базу если его нет
            if message.chat.type != "private":
                self.db.add_user(
                    message.from_user.id, 
                    message.chat.id,
                    message.from_user.username or "",
                    message.from_user.first_name or ""
                )
            
            # Проверяем статус пользователя
            user_global_info = self.db.get_user_global(message.from_user.id)
            is_admin = user_global_info['is_admin']
            is_beta_tester = user_global_info['is_beta_tester']
            
            # Создаем клавиатуру в зависимости от типа чата
            if message.chat.type == "private":
                # В ЛС показываем меню для ЛС
                keyboard = [
                    [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")],
                    [InlineKeyboardButton(text="📖 Помощь по командам", callback_data="help")],
                    [InlineKeyboardButton(text="📢 Наш канал", url=RULES_CHANNEL),
                     InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                ]
                
                # Добавляем кнопку админ-панели только для админов
                if is_admin:
                    keyboard.insert(0, [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
                
                kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
                
                # Определяем приветствие
                user_role = "участник"
                if is_admin:
                    user_role = "админ бота"
                elif is_beta_tester:
                    user_role = "бета тестер"
                
                is_owner = message.from_user.id in ADMIN_IDS
                if is_owner:
                    user_role = f"создатель и повелитель бота {BOT_OWNER_USERNAME}"
                
                text = f"""👋 Привет, {message.from_user.first_name}!

Рад тебя видеть! Я — Puls Bot, твой помощник в управлении группами и чатами.

✨ Что я умею:
• Управление участниками
• Система рангов
• Наказания (муты, баны, предупреждения)
• Автоматические функции
• Настройки групп (новая функция!)

🎮 **Основные команды (просто напиши в чат):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление всех систем
• `помощь` — все доступные команды

📌 **Ты для меня:** {user_role}

Для работы в группе просто добавь меня туда и дай права администратора!

Нажимай на кнопки ниже, чтобы узнать больше ⬇️"""
                
            else:
                # В группе показываем меню для групп
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                chat_role = RANKS.get(user_data['rank'] if user_data else 0, "👤 Участник")
                
                keyboard = [
                    [InlineKeyboardButton(text="📜 Правила чата", callback_data="show_rules"),
                     InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="group_settings")],
                    [InlineKeyboardButton(text="📖 Помощь", callback_data="help"),
                     InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")],
                    [InlineKeyboardButton(text="📢 Наш канал", url=RULES_CHANNEL)]
                ]
                
                kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
                
                text = f"""👋 Привет, {message.from_user.first_name}!

Отлично, теперь я в этой группе и готов помогать с управлением!

✨ **Что я буду делать здесь:**
• Следить за порядком
• Помогать модераторам
• Вести статистику участников

📌 **Твой статус в этом чате:** {chat_role}

🎮 **Основные команды (пиши без /):**
• `пульс` — проверка работы
• `обновить пульс` — обновление (ранг 1+)
• `помощь` — все команды

👮 **Модерация (ранг 1+):**
• `м [время] причина` — мут
• `б причина` — бан  
• `к причина` — кик
• `в причина` — предупреждение

Не забудь подписаться на наш канал с обновлениями! ⬇️"""
            
            await message.reply(text, reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка в /start: {e}")

    async def handle_startpulse(self, message: Message):
        """Обработка /startpulse"""
        await self.handle_start(message)

    async def handle_revivepuls(self, message: Message):
        """Обработка /revivepuls"""
        try:
            # Проверяем права (только создатель чата или админ бота)
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            owner_id = self.db.get_chat_owner(message.chat.id)
            
            if not user_data or (user_data['rank'] < 5 and message.from_user.id != owner_id):
                await message.reply("❌ Только создатель чата может использовать эту команду.")
                return
            
            msg = await message.reply("🔄 Обновляю бота и все настройки группы...")
            await asyncio.sleep(1)
            
            # Загружаем настройки группы
            settings = self.db.get_group_settings(message.chat.id)
            
            # Обновляем правила
            rules = self.db.get_rules(message.chat.id)
            
            result_text = "✅ Бот полностью обновлен!\n\n"
            
            if settings:
                max_warnings = settings.get('max_warnings', DEFAULT_MAX_WARNINGS)
                punishment_type = settings.get('punishment_type', 'м')
                punishment_time = settings.get('punishment_time', '1д')
                
                result_text += f"⚙️ **Настройки группы:**\n"
                result_text += f"• Макс. предупреждений: {max_warnings}\n"
                result_text += f"• Автонаказание: {punishment_type}\n"
                result_text += f"• Время наказания: {punishment_time}\n\n"
            
            if rules and rules != "Правила ещё не установлены. Используй команду 'п текст'":
                result_text += f"📜 **Правила загружены**\n"
            
            result_text += "Все системы работают в штатном режиме! 🚀"
            
            await msg.edit_text(result_text)
            
        except Exception as e:
            logger.error(f"Ошибка в /revivepuls: {e}")

    async def handle_help(self, message: Message):
        """Обработка команды помощи"""
        help_text = """📖 **Доступные команды:**

🎮 **Основные (пиши без /):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление систем (ранг 1+)
• `помощь` — это сообщение
• `правила` — правила чата
• `профиль` — твой профиль
• `ранги` — список рангов
• `стата` — статистика чата

👮 **Модерация (ранг 1+):**
• `м [время] причина` — мут (ответом на сообщение)
• `б причина` — бан (ответом на сообщение)
• `к причина` — кик (ответом на сообщение)
• `в причина` — предупреждение (ответом на сообщение)
• `п [текст]` — установить правила (только создатель чата)

⚙️ **Создатель чата (ранг 5):**
• Настройки группы через кнопку ⚙️

📌 **Триггеры (работают для всех):**
• `пульс` — проверка работы (кд 10 сек)

⚠️ **Ранги:**
0 👤 Участник
1 👮 Младший модератор
2 🛡️ Старший модератор
3 👑 Администратор
4 🌟 Продвинутый админ
5 ✨ СОЗДАТЕЛЬ

📢 **Канал с инструкциями:** https://t.me/RulesPulsOfficial"""
        
        await message.reply(help_text, parse_mode="Markdown")

    async def handle_rules(self, message: Message):
        """Обработка команды правил"""
        try:
            rules = self.db.get_rules(message.chat.id)
            await message.reply(f"📜 **Правила чата:**\n\n{rules}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка показа правил: {e}")
            await message.reply("❌ Ошибка загрузки правил.")

    async def handle_profile(self, message: Message):
        """Обработка команды профиля"""
        try:
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data:
                await message.reply("❌ Ты не зарегистрирован в этом чате.")
                return
            
            rank_name = RANKS.get(user_data['rank'], "👤 Участник")
            username = f"@{user_data['username']}" if user_data['username'] else user_data['first_name']
            
            profile_text = f"""📊 **Твой профиль в этом чате:**

👤 **Имя:** {username}
🎖️ **Ранг:** {rank_name}
⚠️ **Предупреждения:** {user_data['warnings']}
🔇 **Муты:** {user_data['mutes']}
🚫 **Баны:** {user_data['bans']}
💬 **Сообщений:** {user_data['message_count']}
📅 **В чате с:** {user_data['registered_at'][:10] if user_data['registered_at'] else 'Неизвестно'}"""
            
            await message.reply(profile_text, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка показа профиля: {e}")
            await message.reply("❌ Ошибка загрузки профиля.")

    async def handle_ranks(self, message: Message):
        """Обработка команды рангов"""
        ranks_text = "🎖️ **Система рангов:**\n\n"
        for rank_num, rank_name in RANKS.items():
            ranks_text += f"{rank_num}. {rank_name}\n"
        
        ranks_text += "\n📌 **Как получить ранг:**\n"
        ranks_text += "• Ранг 1-2: Выдается администраторами\n"
        ranks_text += "• Ранг 3-4: Только создателем чата\n"
        ranks_text += "• Ранг 5: Автоматически создателю чата"
        
        await message.reply(ranks_text, parse_mode="Markdown")

    async def handle_stats(self, message: Message):
        """Обработка команды статистики"""
        try:
            users = self.db.get_all_users_in_chat(message.chat.id)
            
            if not users:
                await message.reply("📊 В этом чате пока нет статистики.")
                return
            
            total_users = len(users)
            total_messages = sum(user['message_count'] for user in users)
            
            # Сортируем по количеству сообщений
            top_users = sorted(users, key=lambda x: x['message_count'], reverse=True)[:5]
            
            stats_text = f"""📊 **Статистика чата:**

👥 **Всего участников:** {total_users}
💬 **Всего сообщений:** {total_messages}
📈 **Среднее на участника:** {total_messages // total_users if total_users > 0 else 0}

🏆 **Топ по сообщениям:**
"""
            
            for i, user in enumerate(top_users, 1):
                username = f"@{user['username']}" if user['username'] else user['first_name']
                stats_text += f"{i}. {username}: {user['message_count']} сообщ.\n"
            
            await message.reply(stats_text, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка показа статистики: {e}")
            await message.reply("❌ Ошибка загрузки статистики.")

    async def handle_adminpanel_command(self, message: Message):
        """Обработка команды /adminpanelpuls"""
        try:
            # Проверяем, является ли пользователь админом
            is_admin = self.db.is_admin(message.from_user.id)
            is_owner = message.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                if message.chat.type == "private":
                    await message.reply(f"Не для тебя эта кнопка родной, обратись к моему повелителю {BOT_OWNER_USERNAME} чтобы получить админку! (в отсосах примерно 5 тысяч если чо!)")
                else:
                    # В группе отправляем сообщение и в ЛС
                    await message.reply(f"Не для тебя эта кнопка родной, обратись к моему повелителю {BOT_OWNER_USERNAME} чтобы получить админку! (в отсосах примерно 5 тысяч если чо!)")
                    try:
                        await self.bot.send_message(
                            message.from_user.id,
                            f"Не для тебя эта кнопка родной, обратись к моему повелителю {BOT_OWNER_USERNAME} чтобы получить админку! (в отсосах примерно 5 тысяч если чо!)"
                        )
                    except:
                        pass
                return
            
            # Если команда в группе, отправляем админ-панель в ЛС
            if message.chat.type != "private":
                await message.reply("👑 Админ функции доступны только в личных сообщениях бота.")
                try:
                    await self.show_admin_panel(message.from_user.id)
                except Exception as e:
                    logger.error(f"Ошибка отправки админ-панели в ЛС: {e}")
                    await message.reply("❌ Не удалось отправить админ-панель в ЛС. Убедитесь, что вы начали диалог с ботом.")
            else:
                # В ЛС показываем админ-панель
                await self.show_admin_panel(message.from_user.id)
                
        except Exception as e:
            logger.error(f"Ошибка в админ-панели: {e}")
            await message.reply("❌ Не удалось открыть админ-панель.")

    async def show_admin_panel(self, user_id: int):
        """Показывает админ-панель"""
        try:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin")],
                    [InlineKeyboardButton(text="📝 Заметки", callback_data="admin_notes")],
                    [InlineKeyboardButton(text="🧪 Бета тестеры", callback_data="beta_testers")],
                    [InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data="back_to_admin_panel")]
                ]
            )
            
            text = """👑 **Админ-панель**

Здесь ты можешь управлять настройками бота и пользователями.

**Доступные функции:**
• ➕ Добавить админа — добавляет нового администратора бота
• 📝 Заметки — твои личные заметки (доступны только тебе)
• 🧪 Бета тестеры — управление бета тестерами бота

Выбери нужную функцию:"""
            
            await self.bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка показа админ-панели: {e}")
            raise

    # ===================== CALLBACK ОБРАБОТЧИКИ =====================
    
    async def handle_show_rules(self, query: CallbackQuery):
        """Обработка кнопки правил"""
        await query.answer()
        try:
            rules = self.db.get_rules(query.message.chat.id)
            await query.message.answer(f"📜 **Правила чата:**\n\n{rules}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка показа правил: {e}")
            await query.message.answer("❌ Ошибка загрузки правил.")

    async def handle_support(self, query: CallbackQuery):
        """Обработка кнопки поддержки"""
        await query.answer()
        await query.message.answer(
            f"🛠 **Техническая поддержка**\n\n"
            f"Если у тебя есть вопросы или проблемы с ботом:\n"
            f"1. Проверь, что у бота есть права администратора\n"
            f"2. Убедись, что команды вводятся правильно\n"
            f"3. Если проблема не решается, обратись к создателю: {BOT_OWNER_USERNAME}\n\n"
            f"📢 **Наш канал:** {RULES_CHANNEL}",
            parse_mode="Markdown"
        )

    async def handle_help_callback(self, query: CallbackQuery):
        """Обработка кнопки помощи"""
        await query.answer()
        await self.handle_help(query.message)

    async def handle_channel_callback(self, query: CallbackQuery):
        """Обработка кнопки канала"""
        await query.answer()
        await query.message.answer(
            f"📢 **Наш канал с обновлениями и скриптами:**\n"
            f"👉 {RULES_CHANNEL}\n\n"
            "Подпишись, чтобы быть в курсе новых функций!"
        )

    async def handle_bot_rules_callback(self, query: CallbackQuery):
        """Обработка кнопки правил бота"""
        await query.answer()
        await query.message.answer(
            "📋 **Правила использования бота:**\n\n"
            "1. Бот должен иметь права администратора в группе\n"
            "2. Не злоупотребляйте командами модерации\n"
            "3. Ранги выдаются ответственно\n"
            "4. При нарушении правил доступ к боту может быть ограничен\n"
            "5. Создатель бота оставляет за собой право вносить изменения\n\n"
            f"📢 **Канал с инструкциями:** {RULES_CHANNEL}\n\n"
            "Спасибо за использование Puls Bot! 🤖"
        )

    async def handle_group_settings(self, query: CallbackQuery):
        """Обработка кнопки настроек группы"""
        await query.answer()
        
        try:
            # Проверяем, в группе ли мы
            if query.message.chat.type == "private":
                # В ЛС показываем меню добавления группы
                await self.show_group_settings_private(query)
                return
            
            # В группе показываем текущие настройки
            await self.show_group_settings_in_group(query)
            
        except Exception as e:
            logger.error(f"Ошибка в настройках группы: {e}")
            await query.message.answer("❌ Ошибка загрузки настроек.")

    async def show_group_settings_private(self, query: CallbackQuery):
        """Показывает настройки группы в ЛС"""
        try:
            # Получаем группы пользователя
            user_groups = self.db.get_group_settings(user_id=query.from_user.id)
            
            kb_builder = InlineKeyboardBuilder()
            
            if user_groups:
                for group in user_groups:
                    group_name = group.get('group_username', f"Группа {group['chat_id']}")
                    kb_builder.row(InlineKeyboardButton(
                        text=f"⚙️ {group_name}",
                        callback_data=f"config_group_{group['chat_id']}"
                    ))
            
            kb_builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="add_group"))
            kb_builder.row(InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
            
            kb = kb_builder.as_markup()
            
            text = "⚙️ **Настройки групп**\n\n"
            
            if user_groups:
                text += f"У тебя {len(user_groups)} настроенных групп. Выбери группу для настройки:"
            else:
                text += "У тебя пока нет настроенных групп. Нажми 'Добавить группу', чтобы начать."
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка показа настроек в ЛС: {e}")
            await query.message.edit_text("❌ Ошибка загрузки настроек.")

    async def show_group_settings_in_group(self, query: CallbackQuery):
        """Показывает настройки группы в самой группе"""
        try:
            settings = self.db.get_group_settings(query.message.chat.id)
            
            if not settings:
                text = "⚙️ **Настройки группы**\n\n"
                text += "Настройки для этой группы еще не установлены.\n"
                text += "Для настройки перейди в личные сообщения с ботом.\n\n"
                text += "ℹ️ *Эта функция находится на бета тесте, и не все функции могут работать.*"
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⚙️ Настроить в ЛС", url=f"https://t.me/{self.bot_info.username}")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_settings")]
                    ]
                )
            else:
                max_warnings = settings.get('max_warnings', DEFAULT_MAX_WARNINGS)
                punishment_type = settings.get('punishment_type', 'м')
                punishment_time = settings.get('punishment_time', '1д')
                
                punishment_desc = {
                    'м': 'Мут',
                    'б': 'Бан',
                    'к': 'Кик'
                }.get(punishment_type, punishment_type)
                
                text = f"""⚙️ **Настройки группы**

📊 **Текущие настройки:**
⚠️ Макс. предупреждений: {max_warnings}
🔨 Автонаказание при лимите: {punishment_desc}
⏱️ Время наказания: {punishment_time}

ℹ️ *Для изменения настроек перейди в личные сообщения с ботом.*
*Эта функция находится на бета тесте, и не все функции могут работать.*"""
                
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⚙️ Изменить в ЛС", url=f"https://t.me/{self.bot_info.username}")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_settings")]
                    ]
                )
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка показа настроек в группе: {e}")
            await query.message.answer("❌ Ошибка загрузки настроек.")

    async def handle_add_group_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка добавления группы"""
        await query.answer()
        
        await query.message.edit_text(
            "📝 **Добавление группы**\n\n"
            "Отправь ссылку на группу в формате:\n"
            "`https://t.me/название_группы`\n\n"
            "Бот проверит:\n"
            "1. Есть ли он в этой группе\n"
            "2. Являешься ли ты создателем группы\n\n"
            "❌ Отменить: /cancel",
            parse_mode="Markdown"
        )
        
        await state.set_state(GroupSettingsStates.waiting_for_group_link)

    async def handle_close_settings(self, query: CallbackQuery):
        """Обработка закрытия настроек"""
        await query.message.delete()
        await query.answer("Настройки закрыты")

    async def handle_remove_punishment(self, query: CallbackQuery):
        """Обработка снятия наказания"""
        try:
            punishment_id = int(query.data.replace("remove_punish_", ""))
            punishment = self.db.get_punishment_by_id(punishment_id)
            
            if not punishment:
                await query.answer("❌ Наказание не найдено!", show_alert=True)
                return
            
            # Проверяем права пользователя
            user_data = self.db.get_user(query.from_user.id, query.message.chat.id)
            if not user_data or user_data['rank'] < 1:
                await query.answer("❌ У тебя нет прав снимать наказания!", show_alert=True)
                return
            
            # Снимаем наказание
            self.db.remove_punishment(punishment_id)
            
            # Если это мут - восстанавливаем права
            if punishment['type'] in ['мут', 'м']:
                try:
                    permissions = ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=True,
                        can_pin_messages=False
                    )
                    await self.bot.restrict_chat_member(
                        chat_id=punishment['chat_id'],
                        user_id=punishment['user_id'],
                        permissions=permissions
                    )
                except Exception as e:
                    logger.error(f"Ошибка снятия мута: {e}")
            
            # Редактируем сообщение о наказании
            moderator_username = query.from_user.username
            if moderator_username:
                moderator_mention = f"@{moderator_username}"
            else:
                moderator_mention = query.from_user.first_name
            
            await query.message.edit_text(
                f"✅ Наказание снято!\n"
                f"🔓 Снял: {moderator_mention}\n"
                f"👤 Нарушитель: ID {punishment['user_id']}\n"
                f"📝 Причина снятия: по решению модератора",
                reply_markup=None
            )
            
            await query.answer("✅ Наказание снято!", show_alert=True)
            
        except Exception as e:
            logger.error(f"Ошибка снятия наказания: {e}")
            await query.answer("❌ Ошибка снятия наказания!", show_alert=True)

    # ===================== РЕГИСТРАЦИЯ HANDLERS =====================
    
    def register_handlers(self):
        """Регистрация всех обработчиков"""
        
        # ===================== КОМАНДЫ СО СЛЕШОМ =====================
        
        @self.router.message(CommandStart())
        async def start_command(message: Message):
            await self.handle_start(message)
        
        @self.router.message(Command("startpulse"))
        async def startpulse_command(message: Message):
            await self.handle_startpulse(message)
        
        @self.router.message(Command("revivepuls"))
        async def revivepuls_command(message: Message):
            await self.handle_revivepuls(message)
        
        @self.router.message(Command("adminpanelpuls"))
        async def adminpanel_command(message: Message):
            await self.handle_adminpanel_command(message)
        
        # ===================== ОБРАБОТКА СООБЩЕНИЙ В ГРУППАХ =====================
        
        @self.router.message(F.chat.type.in_({"group", "supergroup"}))
        async def handle_group_message(message: Message):
            """Обработчик сообщений в группах"""
            if not message.from_user:
                return
                
            try:
                user = message.from_user
                # Добавляем/обновляем пользователя
                self.db.add_user(user.id, message.chat.id, 
                               user.username or "", user.first_name or "")
                # Увеличиваем счетчик сообщений
                self.db.update_message_count(user.id, message.chat.id)
                
                # Обнаруживаем создателя чата при первом сообщении
                if message.text and message.text.lower() in ['/start', '/startpulse', 'пульс']:
                    await self.detect_chat_owner(message.chat.id)
                
                # Обрабатываем команды без слеша
                if message.text:
                    await self.handle_command_without_slash(message)
                    
            except Exception as e:
                logger.error(f"Ошибка обработки группового сообщения: {e}")
        
        # ===================== CALLBACK ОБРАБОТЧИКИ =====================
        
        @self.router.callback_query(F.data == "show_rules")
        async def show_rules_cb(query: CallbackQuery):
            await self.handle_show_rules(query)
        
        @self.router.callback_query(F.data == "support")
        async def support_cb(query: CallbackQuery):
            await self.handle_support(query)
        
        @self.router.callback_query(F.data == "help")
        async def help_cb(query: CallbackQuery):
            await self.handle_help_callback(query)
        
        @self.router.callback_query(F.data == "channel")
        async def channel_cb(query: CallbackQuery):
            await self.handle_channel_callback(query)
        
        @self.router.callback_query(F.data == "bot_rules")
        async def bot_rules_cb(query: CallbackQuery):
            await self.handle_bot_rules_callback(query)
        
        @self.router.callback_query(F.data == "group_settings")
        async def group_settings_cb(query: CallbackQuery):
            await self.handle_group_settings(query)
        
        @self.router.callback_query(F.data == "admin_panel")
        async def admin_panel_cb(query: CallbackQuery):
            await self.handle_admin_panel_callback(query)
        
        @self.router.callback_query(F.data == "close_settings")
        async def close_settings_cb(query: CallbackQuery):
            await self.handle_close_settings(query)
        
        @self.router.callback_query(F.data == "add_group")
        async def add_group_cb(query: CallbackQuery, state: FSMContext):
            await self.handle_add_group_callback(query, state)
        
        @self.router.callback_query(F.data == "back_to_main")
        async def back_to_main_cb(query: CallbackQuery):
            await self.handle_start(query.message)
        
        @self.router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: CallbackQuery):
            await self.handle_remove_punishment(query)
        
        # ===================== ТРИГГЕРЫ И КОМАНДЫ БЕЗ СЛЕША =====================
        
        @self.router.message(F.text)
        async def handle_text_messages(message: Message):
            """Обработчик текстовых сообщений"""
            if not message.text:
                return
                
            text = message.text.strip()
            
            # Триггеры (не команды) - работают для всех
            if text.lower() == "пульс":
                await self.handle_pulse(message)
                return
                
            elif text.lower() == "обновить пульс":
                await self.handle_update_pulse(message)
                return
            
            # Обработка команд без слеша
            await self.handle_command_without_slash(message)
    
    async def detect_chat_owner(self, chat_id: int):
        """Определяет создателя чата"""
        try:
            # Получаем всех администраторов чата
            admins = await self.bot.get_chat_administrators(chat_id)
            
            for admin in admins:
                if admin.status == ChatMemberStatus.CREATOR:
                    owner_id = admin.user.id
                    current_owner = self.db.get_chat_owner(chat_id)
                    
                    # Если создатель изменился или еще не записан
                    if current_owner != owner_id:
                        self.db.set_chat_owner(chat_id, owner_id)
                        # Устанавливаем создателю ранг 5
                        self.db.set_rank(owner_id, chat_id, 5)
                        logger.info(f"Определен создатель чата {chat_id}: {owner_id}")
                    
                    return owner_id
        except Exception as e:
            logger.error(f"Ошибка определения создателя чата: {e}")
        
        return None
    
    # ===================== FSM HANDLERS =====================
    
    def register_fsm_handlers(self):
        """Регистрация FSM обработчиков"""
        
        @self.router.message(GroupSettingsStates.waiting_for_group_link)
        async def process_group_link_handler(message: Message, state: FSMContext):
            await self.process_group_link_handler(message, state)
        
        @self.router.message(Command("cancel"))
        async def cancel_handler(message: Message, state: FSMContext):
            await state.clear()
            await message.reply("❌ Действие отменено.")
    
    async def process_group_link_handler(self, message: Message, state: FSMContext):
        """Обработка ссылки на группу"""
        try:
            group_link = message.text.strip()
            
            if group_link.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Добавление группы отменено.")
                return
            
            # Извлекаем username группы из ссылки
            if not group_link.startswith("https://t.me/"):
                await message.reply("❌ Неверный формат ссылки. Используй: https://t.me/название_группы")
                return
            
            group_username = group_link.replace("https://t.me/", "").strip()
            
            try:
                # Пытаемся получить информацию о группе
                chat = await self.bot.get_chat(f"@{group_username}")
                
                # Проверяем, является ли бот участником группы
                try:
                    chat_member = await self.bot.get_chat_member(chat.id, self.bot_info.id)
                    if chat_member.status == ChatMemberStatus.LEFT:
                        await message.reply("❌ Бот не добавлен в эту группу. Добавьте бота в группу и дайте права администратора.")
                        return
                except:
                    await message.reply("❌ Бот не добавлен в эту группу. Добавьте бота в группу и дайте права администратора.")
                    return
                
                # Проверяем, является ли пользователь создателем группы
                try:
                    user_chat_member = await self.bot.get_chat_member(chat.id, message.from_user.id)
                    if user_chat_member.status != ChatMemberStatus.CREATOR:
                        await message.reply("❌ Вы не являетесь создателем этой группы. Обратитесь к создателю группы.")
                        return
                except:
                    await message.reply("❌ Вы не являетесь участником этой группы.")
                    return
                
                # Проверяем, не добавлена ли уже эта группа
                existing = self.db.get_group_settings(chat.id)
                if existing:
                    await message.reply(f"✅ Группа @{group_username} уже добавлена! Можете её настраивать.")
                    
                    # Показываем настройки группы
                    await self.show_group_configuration(message, chat.id, group_username)
                else:
                    # Добавляем группу
                    self.db.add_group_setting(chat.id, message.from_user.id, group_username)
                    
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="⚙️ Настроить группу", callback_data=f"config_group_{chat.id}")],
                            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
                        ]
                    )
                    
                    await message.reply(
                        f"✅ Группа @{group_username} добавлена!\n\n"
                        f"Можете её настраивать. Нажмите кнопку ниже:",
                        reply_markup=kb
                    )
                
                await state.clear()
                
            except Exception as e:
                logger.error(f"Ошибка обработки группы: {e}")
                await message.reply("❌ Не удалось найти группу. Проверьте ссылку и убедитесь, что бот добавлен в группу.")
        
        except Exception as e:
            logger.error(f"Ошибка обработки ссылки: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    async def show_group_configuration(self, message: Message, chat_id: int, group_username: str):
        """Показывает конфигурацию группы"""
        try:
            settings = self.db.get_group_settings(chat_id)
            
            if not settings:
                max_warnings = DEFAULT_MAX_WARNINGS
                punishment_type = 'м'
                punishment_time = '1д'
            else:
                max_warnings = settings.get('max_warnings', DEFAULT_MAX_WARNINGS)
                punishment_type = settings.get('punishment_type', 'м')
                punishment_time = settings.get('punishment_time', '1д')
            
            punishment_desc = {
                'м': 'Мут',
                'б': 'Бан',
                'к': 'Кик'
            }.get(punishment_type, punishment_type)
            
            # Создаем клавиатуру
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"⚠️ Максимальное количество: {max_warnings}", callback_data="warn_header")],
                    [
                        InlineKeyboardButton(text="3" + (" ✅" if max_warnings == 3 else ""), callback_data="set_warn_3"),
                        InlineKeyboardButton(text="4" + (" ✅" if max_warnings == 4 else ""), callback_data="set_warn_4"),
                        InlineKeyboardButton(text="5" + (" ✅" if max_warnings == 5 else ""), callback_data="set_warn_5"),
                        InlineKeyboardButton(text="6" + (" ✅" if max_warnings == 6 else ""), callback_data="set_warn_6")
                    ],
                    [InlineKeyboardButton(text=f"⏰ Время и наказание при превышении:", callback_data="punish_header")],
                    [InlineKeyboardButton(text=f"Наказание: {punishment_desc}", callback_data="show_punishment"),
                     InlineKeyboardButton(text=f"Время: {punishment_time}", callback_data="show_time")],
                    [InlineKeyboardButton(text="⚙️ Настроить наказание и время", callback_data="configure_punishment")],
                    [InlineKeyboardButton(text="💾 Сохранить", callback_data=f"save_settings_{chat_id}")],
                    [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_groups")]
                ]
            )
            
            text = f"""⚙️ **Настройки группы: @{group_username}**

📝 **Инструкция:**
1. Выберите максимальное количество предупреждений
2. Настройте наказание и время при превышении лимита
3. Нажмите "Сохранить"

⚠️ **Текущие настройки:**
• Макс. предупреждений: {max_warnings}
• Автонаказание: {punishment_desc}
• Время наказания: {punishment_time}

ℹ️ *Эта функция находится на бета тесте, и не все функции могут работать.*
*Для справки обратитесь в поддержку в главном меню.*"""
            
            await message.reply(text, parse_mode="Markdown", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка показа конфигурации: {e}")
            await message.reply("❌ Ошибка загрузки конфигурации.")

    async def handle_admin_panel_callback(self, query: CallbackQuery):
        """Обработка админ-панели"""
        try:
            # Проверяем права
            is_admin = self.db.is_admin(query.from_user.id)
            is_owner = query.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                await query.answer("❌ У тебя нет прав на эту кнопку!", show_alert=True)
                return
            
            await self.show_admin_panel(query.from_user.id)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в админ-панели callback: {e}")
            await query.answer("❌ Ошибка", show_alert=True)

    async def run(self):
        """Запуск бота"""
        if not await self.check_bot_token():
            logger.error("Неверный токен бота. Завершение работы.")
            return
        
        # Запускаем проверку наказаний
        asyncio.create_task(self.check_expired_punishments())
        
        self.register_handlers()
        self.register_fsm_handlers()
        
        logger.info("Бот запущен и готов к работе!")
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            logger.info("Бот остановлен.")

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    try:
        bot_core = BotCore()
        asyncio.run(bot_core.run())
    except KeyboardInterrupt:
        print("\nБот остановлен.")
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"Ошибка: {e}")
