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
            chat_id INTEGER PRIMARY KEY,
            max_warnings INTEGER DEFAULT 5,
            punishment_type TEXT DEFAULT 'м',
            punishment_time TEXT DEFAULT '1д',
            settings_json TEXT
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
                      moderator_id: int, reason: str, end_time: datetime, 
                      message_id: int = None):
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO punishments 
                      (chat_id, user_id, type, moderator_id, reason, end_time, message_id) 
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (chat_id, user_id, punishment_type, moderator_id, reason, 
                    end_time.isoformat(), message_id))
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

    def get_group_settings(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM group_settings WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        if result:
            return dict(result)
        return None

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
        self.user_cooldowns = {}  # Для хранения кд пользователей

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
                
                # Проверяем создателя чата
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
        
        @self.router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: CallbackQuery):
            await self.handle_remove_punishment(query)
        
        @self.router.callback_query(F.data.startswith("settings_"))
        async def settings_callback(query: CallbackQuery):
            await self.handle_settings_callback(query)
        
        @self.router.callback_query(F.data.startswith("warn_set_"))
        async def warn_set_callback(query: CallbackQuery):
            await self.handle_warn_set_callback(query)
        
        @self.router.callback_query(F.data == "add_group")
        async def add_group_callback(query: CallbackQuery):
            await self.handle_add_group_callback(query)
        
        @self.router.callback_query(F.data == "configure_punishment")
        async def configure_punishment_callback(query: CallbackQuery):
            await self.handle_configure_punishment_callback(query)
        
        @self.router.callback_query(F.data == "configure_time")
        async def configure_time_callback(query: CallbackQuery):
            await self.handle_configure_time_callback(query)
        
        @self.router.callback_query(F.data == "edit_punishment")
        async def edit_punishment_callback(query: CallbackQuery):
            await self.handle_edit_punishment_callback(query)
        
        @self.router.callback_query(F.data == "edit_time")
        async def edit_time_callback(query: CallbackQuery):
            await self.handle_edit_time_callback(query)
        
        @self.router.callback_query(F.data == "back_to_settings")
        async def back_to_settings_callback(query: CallbackQuery):
            await self.handle_back_to_settings_callback(query)
        
        @self.router.callback_query(F.data == "save_settings")
        async def save_settings_callback(query: CallbackQuery):
            await self.handle_save_settings_callback(query)
        
        # Админ панель callback обработчики
        @self.router.callback_query(F.data == "add_admin")
        async def add_admin_callback(query: CallbackQuery, state: FSMContext):
            await self.handle_add_admin_callback(query, state)
        
        @self.router.callback_query(F.data == "admin_notes")
        async def admin_notes_callback(query: CallbackQuery):
            await self.handle_admin_notes_callback(query)
        
        @self.router.callback_query(F.data == "add_note")
        async def add_note_callback(query: CallbackQuery, state: FSMContext):
            await self.handle_add_note_callback(query, state)
        
        @self.router.callback_query(F.data.startswith("view_note_"))
        async def view_note_callback(query: CallbackQuery):
            await self.handle_view_note_callback(query)
        
        @self.router.callback_query(F.data == "back_to_admin_panel")
        async def back_to_admin_panel_callback(query: CallbackQuery):
            await self.handle_back_to_admin_panel_callback(query)
        
        @self.router.callback_query(F.data == "back_to_notes")
        async def back_to_notes_callback(query: CallbackQuery):
            await self.handle_back_to_notes_callback(query)
        
        @self.router.callback_query(F.data == "beta_testers")
        async def beta_testers_callback(query: CallbackQuery):
            await self.handle_beta_testers_callback(query)
        
        @self.router.callback_query(F.data == "add_beta_tester")
        async def add_beta_tester_callback(query: CallbackQuery, state: FSMContext):
            await self.handle_add_beta_tester_callback(query, state)
        
        @self.router.callback_query(F.data.startswith("beta_tester_"))
        async def beta_tester_detail_callback(query: CallbackQuery):
            await self.handle_beta_tester_detail_callback(query)
        
        @self.router.callback_query(F.data.startswith("edit_beta_"))
        async def edit_beta_tester_callback(query: CallbackQuery, state: FSMContext):
            await self.handle_edit_beta_tester_callback(query, state)
        
        @self.router.callback_query(F.data.startswith("remove_beta_"))
        async def remove_beta_tester_callback(query: CallbackQuery):
            await self.handle_remove_beta_tester_callback(query)
        
        @self.router.callback_query(F.data == "back_to_beta_testers")
        async def back_to_beta_testers_callback(query: CallbackQuery):
            await self.handle_back_to_beta_testers_callback(query)
        
        # ===================== ТРИГГЕРЫ И КОМАНДЫ БЕЗ СЛЕША =====================
        
        @self.router.message(F.text)
        async def handle_text_messages(message: Message):
            """Обработчик текстовых сообщений"""
            if not message.text:
                return
                
            text = message.text.strip()
            
            # Триггеры (не команды) - работают для всех
            if text.lower() == "пульс":
                # Проверяем кд для обычных пользователей
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] == 0:
                    if not self.db.check_cooldown(message.from_user.id, message.chat.id, "пульс", 10):
                        await message.reply("⏳ Подождите 10 секунд перед использованием этой команды снова.")
                        return
                
                response = random.choice([
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
                ])
                await message.reply(response)
                return
                
            elif text.lower() == "обновить пульс":
                # Проверяем права для этой команды
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 1:
                    await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 1 или выше.")
                    return
                
                # Проверяем кд для обычных пользователей
                if user_data['rank'] == 1:
                    if not self.db.check_cooldown(message.from_user.id, message.chat.id, "обновить пульс", 10):
                        await message.reply("⏳ Подождите 10 секунд перед использованием этой команды снова.")
                        return
                
                msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
                await asyncio.sleep(0.8)
                
                # Обновляем настройки группы
                settings = self.db.get_group_settings(message.chat.id)
                if settings:
                    max_warnings = settings.get('max_warnings', DEFAULT_MAX_WARNINGS)
                    await msg1.edit_text(f"✅ Все функции применены, бот работает нормально\n"
                                        f"⚙️ Настройки группы обновлены (макс. варнов: {max_warnings})")
                else:
                    await msg1.edit_text("✅ Все функции применены, бот работает нормально")
                return
            
            # Обработка команд без слеша (только в группах)
            if message.chat.type in ["group", "supergroup"]:
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
    
    async def handle_start(self, message: Message):
        """Обработка /start"""
        # Проверяем статус пользователя
        user_global_info = self.db.get_user_global(message.from_user.id)
        is_admin = user_global_info['is_admin']
        is_beta_tester = user_global_info['is_beta_tester']
        
        # Создаем клавиатуру
        keyboard = [
            [InlineKeyboardButton(text="📜 Правила чата", callback_data="show_rules"),
             InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")],
            [InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="group_settings")],
            [InlineKeyboardButton(text="📖 Помощь по командам", callback_data="help")],
            [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts"),
             InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
        ]
        
        # Добавляем кнопку админ-панели только для админов
        if is_admin:
            keyboard.insert(1, [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        # Определяем приветствие в зависимости от статуса
        user_role = "участник"
        if is_admin:
            user_role = "админ бота"
        elif is_beta_tester:
            user_role = "бета тестер"
        
        # Проверяем, является ли пользователь создателем бота
        is_owner = message.from_user.id in ADMIN_IDS
        
        if is_owner:
            user_role = f"создатель и повелитель бота {BOT_OWNER_USERNAME}"
        
        if message.chat.type == "private":
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
            # Получаем информацию о пользователе в этом чате
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            chat_role = RANKS.get(user_data['rank'] if user_data else 0, "👤 Участник") if user_data else "👤 Участник"
            
            text = f"""👋 Привет, {message.from_user.first_name}!

Отлично, теперь я в этой группе и готов помогать с управлением!

✨ **Что я буду делать здесь:**
• Следить за порядком
• Помогать модераторам
• Вести статистику участников

📌 **Твой статус в этом чате:** {chat_role}
📌 **Ты для бота:** {user_role}

🎮 **Основные команды (пиши без /):**
• `пульс` — проверка работы
• `обновить пульс` — обновление
• `помощь` — все команды

👮 **Модерация:**
• `м 30м причина` — мут на 30 минут
• `б причина` — бан  
• `к причина` — кик
• `в причина` — предупреждение

Не забудь подписаться на наш канал с обновлениями! ⬇️"""
        
        await message.reply(text, reply_markup=kb)
    
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
    
    async def handle_admin_panel_callback(self, query: CallbackQuery):
        """Обработка нажатия на кнопку админ-панели"""
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
    
    async def handle_add_admin_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка добавления админа"""
        try:
            # Проверяем права
            is_owner = query.from_user.id in ADMIN_IDS
            if not is_owner:
                await query.answer("❌ Только создатель бота может добавлять админов!", show_alert=True)
                return
            
            await query.message.edit_text(
                "👑 **Добавление администратора**\n\n"
                "Напиши ID пользователя или его юзернейм (например: 123456789 или @username)\n\n"
                "❌ Отменить: /cancel",
                parse_mode="Markdown"
            )
            
            await state.set_state(AdminPanelStates.waiting_for_admin_id)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в добавлении админа: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_admin_notes_callback(self, query: CallbackQuery):
        """Обработка заметок админа"""
        try:
            # Проверяем права
            is_admin = self.db.is_admin(query.from_user.id)
            is_owner = query.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                await query.answer("❌ У тебя нет прав на эту кнопку!", show_alert=True)
                return
            
            # Получаем заметки админа
            notes = self.db.get_admin_notes(query.from_user.id)
            
            if not notes:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ Добавить заметку", callback_data="add_note")],
                        [InlineKeyboardButton(text="↩️ Вернуться в админ-панель", callback_data="back_to_admin_panel")]
                    ]
                )
                
                text = "📝 **Мои заметки**\n\nУ тебя пока нет заметок. Нажми 'Добавить заметку', чтобы создать первую."
            else:
                # Создаем клавиатуру с заметками
                kb_builder = InlineKeyboardBuilder()
                
                for note in notes:
                    kb_builder.row(InlineKeyboardButton(
                        text=f"📌 {note['title'][:30]}{'...' if len(note['title']) > 30 else ''}",
                        callback_data=f"view_note_{note['id']}"
                    ))
                
                kb_builder.row(InlineKeyboardButton(text="➕ Добавить заметку", callback_data="add_note"))
                kb_builder.row(InlineKeyboardButton(text="↩️ Вернуться в админ-панель", callback_data="back_to_admin_panel"))
                
                kb = kb_builder.as_markup()
                
                text = f"📝 **Мои заметки**\n\nУ тебя {len(notes)} заметок. Выбери заметку для просмотра:"
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в заметках админа: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_add_note_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка добавления заметки"""
        try:
            # Проверяем права
            is_admin = self.db.is_admin(query.from_user.id)
            is_owner = query.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                await query.answer("❌ У тебя нет прав на эту кнопку!", show_alert=True)
                return
            
            await query.message.edit_text(
                "📝 **Добавление заметки**\n\n"
                "Напиши название заметки (например: 'Идеи для бота'):\n\n"
                "❌ Отменить: /cancel",
                parse_mode="Markdown"
            )
            
            await state.set_state(AdminPanelStates.waiting_for_note_title)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в добавлении заметки: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_view_note_callback(self, query: CallbackQuery):
        """Обработка просмотра заметки"""
        try:
            note_id = int(query.data.replace("view_note_", ""))
            note = self.db.get_admin_note(note_id)
            
            if not note:
                await query.answer("❌ Заметка не найдена!", show_alert=True)
                return
            
            # Проверяем, принадлежит ли заметка этому админу
            if note['admin_id'] != query.from_user.id:
                await query.answer("❌ Эта заметка не твоя!", show_alert=True)
                return
            
            # Форматируем дату создания
            created_at = datetime.fromisoformat(note['created_at'])
            created_str = created_at.strftime("%d.%m.%Y %H:%M")
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Вернуться к заметкам", callback_data="back_to_notes")]
                ]
            )
            
            text = f"""📝 **Заметка: {note['title']}**

{note['content']}

📅 Создано: {created_str}"""
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в просмотре заметки: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_back_to_notes_callback(self, query: CallbackQuery):
        """Возврат к списку заметок"""
        await self.handle_admin_notes_callback(query)
    
    async def handle_back_to_admin_panel_callback(self, query: CallbackQuery):
        """Возврат в админ-панель"""
        await self.handle_admin_panel_callback(query)
    
    async def handle_beta_testers_callback(self, query: CallbackQuery):
        """Обработка бета тестеров"""
        try:
            # Проверяем права
            is_admin = self.db.is_admin(query.from_user.id)
            is_owner = query.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                await query.answer("❌ У тебя нет прав на эту кнопку!", show_alert=True)
                return
            
            # Получаем бета тестеров
            beta_testers = self.db.get_all_beta_testers()
            
            if not beta_testers:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ Добавить бета тестера", callback_data="add_beta_tester")],
                        [InlineKeyboardButton(text="↩️ Вернуться в админ-панель", callback_data="back_to_admin_panel")]
                    ]
                )
                
                text = "🧪 **Бета тестеры**\n\nПока нет бета тестеров. Нажми 'Добавить бета тестера', чтобы добавить первого."
            else:
                # Создаем клавиатуру с бета тестерами
                kb_builder = InlineKeyboardBuilder()
                
                for tester in beta_testers:
                    display_name = f"@{tester['username']}" if tester['username'] else tester['first_name']
                    kb_builder.row(InlineKeyboardButton(
                        text=f"🧪 {display_name[:30]}{'...' if len(display_name) > 30 else ''}",
                        callback_data=f"beta_tester_{tester['user_id']}"
                    ))
                
                kb_builder.row(InlineKeyboardButton(text="➕ Добавить бета тестера", callback_data="add_beta_tester"))
                kb_builder.row(InlineKeyboardButton(text="↩️ Вернуться в админ-панель", callback_data="back_to_admin_panel"))
                
                kb = kb_builder.as_markup()
                
                text = f"🧪 **Бета тестеры**\n\nВсего бета тестеров: {len(beta_testers)}\n\nВыбери бета тестера для управления:"
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в бета тестерах: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_add_beta_tester_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка добавления бета тестера"""
        try:
            # Проверяем права
            is_admin = self.db.is_admin(query.from_user.id)
            is_owner = query.from_user.id in ADMIN_IDS
            
            if not (is_admin or is_owner):
                await query.answer("❌ У тебя нет прав на эту кнопку!", show_alert=True)
                return
            
            await query.message.edit_text(
                "🧪 **Добавление бета тестера**\n\n"
                "Напиши юзернейм пользователя (например: @username):\n\n"
                "⚠️ **Внимание:** Юзернейм должен начинаться с @ и содержать только английские буквы, цифры и подчеркивания.\n"
                "Максимум 30 символов.\n\n"
                "❌ Отменить: /cancel",
                parse_mode="Markdown"
            )
            
            await state.set_state(AdminPanelStates.waiting_for_beta_tester_username)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в добавлении бета тестера: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_beta_tester_detail_callback(self, query: CallbackQuery):
        """Обработка деталей бета тестера"""
        try:
            user_id = int(query.data.replace("beta_tester_", ""))
            tester = self.db.get_beta_tester(user_id)
            
            if not tester:
                await query.answer("❌ Бета тестер не найден!", show_alert=True)
                return
            
            # Форматируем дату добавления
            added_at = datetime.fromisoformat(tester['added_at'])
            added_str = added_at.strftime("%d.%m.%Y %H:%M")
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Изменить юзернейм", callback_data=f"edit_beta_{user_id}")],
                    [InlineKeyboardButton(text="🗑️ Исключить бета тестера", callback_data=f"remove_beta_{user_id}")],
                    [InlineKeyboardButton(text="↩️ Вернуться к бета тестерам", callback_data="back_to_beta_testers")]
                ]
            )
            
            display_name = f"@{tester['username']}" if tester['username'] else tester['first_name']
            
            text = f"""🧪 **Бета тестер: {display_name}**

📋 **Информация:**
• ID: `{tester['user_id']}`
• Имя: {tester['first_name']}
• Юзернейм: @{tester['username'] or 'не указан'}
• Добавлен: {added_str}
• Добавил: ID {tester['added_by']}

Выбери действие:"""
            
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в деталях бета тестера: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_edit_beta_tester_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка изменения юзернейма бета тестера"""
        try:
            user_id = int(query.data.replace("edit_beta_", ""))
            tester = self.db.get_beta_tester(user_id)
            
            if not tester:
                await query.answer("❌ Бета тестер не найден!", show_alert=True)
                return
            
            # Сохраняем ID бета тестера в состоянии
            await state.update_data(beta_tester_id=user_id)
            
            await query.message.edit_text(
                f"✏️ **Изменение юзернейма бета тестера**\n\n"
                f"Текущий юзернейм: @{tester['username'] or 'не указан'}\n\n"
                f"Напиши новый юзернейм (например: @newusername):\n\n"
                f"⚠️ **Внимание:** Юзернейм должен начинаться с @ и содержать только английские буквы, цифры и подчеркивания.\n"
                f"Максимум 30 символов.\n\n"
                f"❌ Отменить: /cancel",
                parse_mode="Markdown"
            )
            
            await state.set_state(AdminPanelStates.waiting_for_beta_tester_new_username)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в изменении бета тестера: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_remove_beta_tester_callback(self, query: CallbackQuery):
        """Обработка удаления бета тестера"""
        try:
            user_id = int(query.data.replace("remove_beta_", ""))
            tester = self.db.get_beta_tester(user_id)
            
            if not tester:
                await query.answer("❌ Бета тестер не найден!", show_alert=True)
                return
            
            # Удаляем бета тестера
            self.db.remove_beta_tester(user_id)
            
            display_name = f"@{tester['username']}" if tester['username'] else tester['first_name']
            
            await query.answer(f"✅ Бета тестер {display_name} удален!", show_alert=True)
            
            # Возвращаемся к списку бета тестеров
            await self.handle_beta_testers_callback(query)
            
        except Exception as e:
            logger.error(f"Ошибка в удалении бета тестера: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
    
    async def handle_back_to_beta_testers_callback(self, query: CallbackQuery):
        """Возврат к списку бета тестеров"""
        await self.handle_beta_testers_callback(query)
    
    # ===================== HANDLERS ДЛЯ FSM СОСТОЯНИЙ (ВЫНЕСЕНЫ) =====================
    
    async def process_admin_id_handler(self, message: Message, state: FSMContext):
        """Обработка ID админа"""
        try:
            admin_input = message.text.strip()
            
            if admin_input.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Добавление админа отменено.")
                return
            
            user_id = None
            username = None
            first_name = "Неизвестно"
            
            # Пытаемся получить информацию о пользователе
            try:
                # Если это числовой ID
                if admin_input.isdigit():
                    user_id = int(admin_input)
                    try:
                        user = await self.bot.get_chat(user_id)
                        username = user.username
                        first_name = user.first_name
                    except:
                        # Если не можем получить информацию, все равно добавляем
                        pass
                # Если это юзернейм
                elif admin_input.startswith('@'):
                    username = admin_input[1:]
                    # Пытаемся найти пользователя по юзернейму
                    try:
                        # Это сложно сделать напрямую, поэтому просим отправить ID
                        await message.reply(
                            "⚠️ Не могу найти пользователя по юзернейму.\n"
                            "Пожалуйста, отправь числовой ID пользователя."
                        )
                        return
                    except:
                        pass
                else:
                    await message.reply(
                        "❌ Неверный формат. Отправь числовой ID или юзернейм (начиная с @).\n"
                        "Примеры: 123456789 или @username"
                    )
                    return
                
                # Добавляем админа
                if user_id:
                    self.db.add_admin(user_id, username, first_name, message.from_user.id)
                    
                    await message.reply(
                        f"✅ Админ добавлен!\n"
                        f"• ID: `{user_id}`\n"
                        f"• Имя: {first_name}\n"
                        f"• Юзернейм: @{username or 'не указан'}\n\n"
                        f"Теперь у пользователя есть доступ к админ-панели.",
                        parse_mode="Markdown"
                    )
                    
                    # Пытаемся уведомить нового админа
                    try:
                        await self.bot.send_message(
                            user_id,
                            f"🎉 Поздравляем! Тебя добавили в админы бота @{self.bot_info.username}!\n\n"
                            f"Теперь у тебя есть доступ к админ-панели. Используй команду /adminpanelpuls для доступа."
                        )
                    except:
                        pass
                else:
                    await message.reply("❌ Не удалось добавить админа. Убедитесь, что ID правильный.")
                
            except Exception as e:
                logger.error(f"Ошибка добавления админа: {e}")
                await message.reply("❌ Не удалось добавить админа. Проверьте правильность данных.")
            
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка обработки ID админа: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    async def process_note_title_handler(self, message: Message, state: FSMContext):
        """Обработка названия заметки"""
        try:
            title = message.text.strip()
            
            if title.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Добавление заметки отменено.")
                return
            
            if len(title) < 1:
                await message.reply("❌ Название заметки не может быть пустым.")
                return
            
            if len(title) > 100:
                await message.reply("❌ Название заметки слишком длинное (макс. 100 символов).")
                return
            
            # Сохраняем название в состоянии
            await state.update_data(note_title=title)
            
            await message.reply(
                "📝 **Продолжаем добавление заметки**\n\n"
                "Теперь напиши содержание заметки (минимум 2 символа):\n\n"
                "❌ Отменить: /cancel",
                parse_mode="Markdown"
            )
            
            await state.set_state(AdminPanelStates.waiting_for_note_content)
            
        except Exception as e:
            logger.error(f"Ошибка обработки названия заметки: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    async def process_note_content_handler(self, message: Message, state: FSMContext):
        """Обработка содержания заметки"""
        try:
            content = message.text.strip()
            
            if content.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Добавление заметки отменено.")
                return
            
            if len(content) < 2:
                await message.reply("❌ Содержание заметки должно быть минимум 2 символа.")
                return
            
            # Получаем название из состояния
            data = await state.get_data()
            title = data.get('note_title')
            
            if not title:
                await message.reply("❌ Ошибка: не найдено название заметки.")
                await state.clear()
                return
            
            # Добавляем заметку в базу
            note_id = self.db.add_admin_note(message.from_user.id, title, content)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📝 К заметкам", callback_data="admin_notes")],
                    [InlineKeyboardButton(text="👑 В админ-панель", callback_data="back_to_admin_panel")]
                ]
            )
            
            await message.reply(
                f"✅ Заметка добавлена!\n\n"
                f"📌 **Название:** {title}\n"
                f"📝 **Содержание:** {content[:50]}{'...' if len(content) > 50 else ''}\n\n"
                f"ID заметки: {note_id}",
                reply_markup=kb
            )
            
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка обработки содержания заметки: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    async def process_beta_tester_username_handler(self, message: Message, state: FSMContext):
        """Обработка юзернейма бета тестера"""
        try:
            username_input = message.text.strip()
            
            if username_input.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Добавление бета тестера отменено.")
                return
            
            # Проверяем формат юзернейма
            if not username_input.startswith('@'):
                await message.reply("❌ Юзернейм должен начинаться с @.")
                return
            
            username = username_input[1:]
            
            # Проверяем длину
            if len(username) > 30:
                await message.reply("❌ Юзернейм слишком длинный (макс. 30 символов).")
                return
            
            # Проверяем допустимые символы
            if not re.match(r'^[a-zA-Z0-9_]+$', username):
                await message.reply("❌ Юзернейм может содержать только английские буквы, цифры и подчеркивания.")
                return
            
            # Здесь нужно получить ID пользователя по юзернейму
            # Это сложная задача в Telegram Bot API, поэтому просто сохраняем юзернейм
            # На практике нужно будет получить ID другими способами
            
            await message.reply(
                "⚠️ **Внимание:** Для полной функциональности необходимо знать ID пользователя.\n\n"
                f"Юзернейм @{username} принят, но для полной интеграции пользователю нужно:\n"
                "1. Написать боту в ЛС\n"
                "2. Или предоставить его ID\n\n"
                "Пока что статус бета тестера будет работать частично."
            )
            
            # Сохраняем в базу с временным ID 0
            # На практике здесь нужно получить реальный ID
            temp_user_id = 0  # Временное значение
            self.db.add_beta_tester(temp_user_id, username, "Бета тестер", message.from_user.id)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🧪 К бета тестерам", callback_data="beta_testers")],
                    [InlineKeyboardButton(text="👑 В админ-панель", callback_data="back_to_admin_panel")]
                ]
            )
            
            await message.reply(
                f"✅ Бета тестер @{username} добавлен!\n\n"
                f"⚠️ **Примечание:** Для полной функциональности нужно получить ID пользователя.\n"
                f"Пользователь может написать боту в ЛС, чтобы система автоматически получила его ID.",
                reply_markup=kb
            )
            
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка обработки юзернейма бета тестера: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    async def process_beta_tester_new_username_handler(self, message: Message, state: FSMContext):
        """Обработка нового юзернейма бета тестера"""
        try:
            username_input = message.text.strip()
            
            if username_input.lower() == '/cancel':
                await state.clear()
                await message.reply("❌ Изменение юзернейма отменено.")
                return
            
            # Проверяем формат юзернейма
            if not username_input.startswith('@'):
                await message.reply("❌ Юзернейм должен начинаться с @.")
                return
            
            username = username_input[1:]
            
            # Проверяем длину
            if len(username) > 30:
                await message.reply("❌ Юзернейм слишком длинный (макс. 30 символов).")
                return
            
            # Проверяем допустимые символы
            if not re.match(r'^[a-zA-Z0-9_]+$', username):
                await message.reply("❌ Юзернейм может содержать только английские буквы, цифры и подчеркивания.")
                return
            
            # Получаем ID бета тестера из состояния
            data = await state.get_data()
            user_id = data.get('beta_tester_id')
            
            if not user_id:
                await message.reply("❌ Ошибка: не найден ID бета тестера.")
                await state.clear()
                return
            
            # Обновляем юзернейм
            self.db.update_beta_tester_username(user_id, username)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🧪 К бета тестерам", callback_data="beta_testers")],
                    [InlineKeyboardButton(text="👑 В админ-панель", callback_data="back_to_admin_panel")]
                ]
            )
            
            await message.reply(
                f"✅ Юзернейм бета тестера обновлен на @{username}!",
                reply_markup=kb
            )
            
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка обработки нового юзернейма бета тестера: {e}")
            await message.reply("❌ Ошибка обработки.")
            await state.clear()
    
    # ... [остальной код остается таким же] ...

    async def run(self):
        """Запуск бота"""
        if not await self.check_bot_token():
            logger.error("Неверный токен бота. Завершение работы.")
            return
        
        # Запускаем проверку наказаний
        asyncio.create_task(self.check_expired_punishments())
        
        self.register_handlers()
        
        # Регистрируем FSM обработчики отдельно
        self.register_fsm_handlers()
        
        logger.info("Бот запущен и готов к работе!")
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            logger.info("Бот остановлен.")

# ===================== ВНЕШНИЕ ОБРАБОТЧИКИ FSM =====================

# Создаем глобальные обработчики FSM, которые будут регистрироваться отдельно
# Эти обработчики должны быть определены вне класса BotCore

# Глобальный router для FSM обработчиков
fsm_router = Router()

@fsm_router.message(AdminPanelStates.waiting_for_admin_id)
async def process_admin_id_global(message: Message, state: FSMContext):
    """Глобальный обработчик ID админа"""
    # Этот обработчик должен вызывать метод BotCore
    # Для этого нужно получить экземпляр BotCore
    # В реальном коде это делается через dependency injection
    pass

@fsm_router.message(AdminPanelStates.waiting_for_note_title)
async def process_note_title_global(message: Message, state: FSMContext):
    """Глобальный обработчик названия заметки"""
    pass

@fsm_router.message(AdminPanelStates.waiting_for_note_content)
async def process_note_content_global(message: Message, state: FSMContext):
    """Глобальный обработчик содержания заметки"""
    pass

@fsm_router.message(AdminPanelStates.waiting_for_beta_tester_username)
async def process_beta_tester_username_global(message: Message, state: FSMContext):
    """Глобальный обработчик юзернейма бета тестера"""
    pass

@fsm_router.message(AdminPanelStates.waiting_for_beta_tester_new_username)
async def process_beta_tester_new_username_global(message: Message, state: FSMContext):
    """Глобальный обработчик нового юзернейма бета тестера"""
    pass

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
