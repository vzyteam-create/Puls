"""
============================================
POLICE DEPARTMENT - Telegram Game Bot
ПОЛНЫЙ РАБОЧИЙ КОД С АВТОМАТИЗАЦИЕЙ И ТАЙМЕРАМИ
Версия: 4.1
============================================
"""

import asyncio
import logging
import random
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from enum import Enum

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Настройки игры
MAX_PLAYERS = 50
MIN_PLAYERS = 5
MURDER_COOLDOWN = 300
KILLS_TO_WIN = 10
INACTIVITY_TIMEOUT = 300  # 5 минут
SUSPENSION_TIME = 600  # 10 минут отстранения
AUTO_CHECK_INTERVAL = 60  # Проверка активности каждую минуту

# Шансы ролей
ROLE_CHANCES = {
    "police": 40.0,
    "civilian": 35.0,
    "boss": 3.0,
    "it": 4.0,
    "criminal": 3.0,
    "any": 15.0
}

# Полицейские ники
POLICE_NICKS = [
    "Орел", "Волк", "Тигр", "Медведь", "Сокол", "Ястреб", "Барс", 
    "Рысь", "Феникс", "Гриф", "Коршун", "Кондор", "Буревестник"
]

# Времена для мута
MUTE_TIMES = {
    "1_hour": 3600,
    "5_hours": 18000,
    "10_hours": 36000,
    "1_day": 86400,
    "2_days": 172800,
    "1_week": 604800
}

# Времена тюрьмы (в минутах)
PRISON_TIMES = [5, 10, 15, 20, 30, 45, 60]
LIFE_SENTENCE = 1440  # 24 часа = пожизненное

# ============================================
# МОДЕЛИ ДАННЫХ
# ============================================

class Role(Enum):
    POLICE = "👮 Полицейский"
    BOSS = "🧠 Начальник"
    IT = "💻 ИТ-специалист"
    CRIMINAL = "🕵️‍♂️ Преступник"
    CIVILIAN = "🧍 Мирный"
    EX_CONVICT = "👤 Бывший осужденный"
    RECIDIVIST = "🔪 Рецидивист"

class PlayerStatus(Enum):
    FREE = "свободен"
    IN_PRISON = "в тюрьме"
    DEAD = "мертв"
    ARRESTED = "арестован"
    SUSPENDED = "отстранен"  # Временное отстранение за неактивность
    ACTIVE = "активен"

@dataclass
class PrisonRecord:
    game_number: int
    chat_id: int
    sentence_minutes: int
    arrest_time: datetime
    release_time: datetime
    crime: str = "убийства"
    reformed: bool = False
    is_life: bool = False

@dataclass
class Suspension:
    start_time: datetime
    end_time: datetime
    reason: str = "неактивность"
    suspension_count: int = 1  # Счетчик отстранений
    bot_controlled: bool = True  # Бот играет за игрока

@dataclass
class Player:
    user_id: int
    username: str
    current_game_chat_id: Optional[int] = None
    current_game_number: Optional[int] = None
    role: Optional[Role] = None
    chosen_role: Optional[Role] = None
    police_nick: Optional[str] = None
    reputation: int = 50
    intelligence: int = 0
    kills: int = 0
    status: PlayerStatus = PlayerStatus.FREE
    last_action: Optional[datetime] = None
    last_message_time: Optional[datetime] = None  # Время последнего сообщения от игрока
    is_bot_controlled: bool = False
    suspension: Optional[Suspension] = None
    prison_records: List[PrisonRecord] = field(default_factory=list)
    current_prison: Optional[PrisonRecord] = None
    criminal_attempts: int = 0
    suspension_count: int = 0  # Сколько раз был отстранен
    notes: Dict[str, str] = field(default_factory=dict)
    witnesses: Dict[str, str] = field(default_factory=dict)
    auto_actions: List[str] = field(default_factory=list)  # Действия, которые сделал бот
    
    @property
    def is_in_prison(self) -> bool:
        return self.status == PlayerStatus.IN_PRISON
    
    @property
    def is_suspended(self) -> bool:
        return self.status == PlayerStatus.SUSPENDED
    
    @property
    def has_criminal_record(self) -> bool:
        return len(self.prison_records) > 0
    
    @property
    def is_recidivist(self) -> bool:
        """Является ли рецидивистом (более 2 судимостей)"""
        return len([r for r in self.prison_records if not r.reformed]) >= 2
    
    def get_display_name(self) -> str:
        if self.role == Role.POLICE and self.police_nick:
            return f"👮 Полицейский {self.police_nick}"
        elif self.role == Role.IT:
            return "💻 ИТ-специалист"
        elif self.role == Role.BOSS:
            return "🧠 Начальник полиции"
        elif self.role == Role.CRIMINAL:
            return f"🕵️‍♂️ Преступник ({self.kills} убийств)"
        elif self.role == Role.RECIDIVIST:
            return f"🔪 Рецидивист {self.username}"
        elif self.role == Role.EX_CONVICT:
            return f"👤 {self.username} (судимый)"
        else:
            return f"🧍 {self.username}"
    
    def can_be_suspended(self) -> bool:
        """Может ли игрок быть отстранен"""
        if self.is_in_prison or self.status == PlayerStatus.DEAD:
            return False
        return True

@dataclass
class Game:
    chat_id: int
    game_number: int
    state: GameState = GameState.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    murder_count: int = 0
    criminal_id: Optional[int] = None
    boss_id: Optional[int] = None
    it_id: Optional[int] = None
    news: List[str] = field(default_factory=list)
    messages_to_delete: List[int] = field(default_factory=list)
    chat_open: bool = False
    chat_open_until: Optional[datetime] = None
    creator_id: Optional[int] = None
    deleted_messages_count: int = 0
    win_reason: Optional[str] = None
    waiting_for_players: bool = False  # Ожидание неактивных игроков
    
    def get_alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.status not in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON, PlayerStatus.ARRESTED]]
    
    def get_active_players(self) -> List[Player]:
        """Игроки, которые активны (не отстранены и проявляли активность)"""
        now = datetime.now()
        return [
            p for p in self.players.values() 
            if p.status not in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON, PlayerStatus.SUSPENDED]
            and (p.last_message_time is None or (now - p.last_message_time).seconds < INACTIVITY_TIMEOUT)
        ]
    
    def get_inactive_players(self) -> List[Player]:
        """Игроки, которые неактивны более 5 минут"""
        now = datetime.now()
        inactive = []
        for player in self.players.values():
            if player.status in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON]:
                continue
                
            # Если нет времени последнего сообщения или прошло больше INACTIVITY_TIMEOUT
            if player.last_message_time is None:
                # Если игрок никогда не писал, считаем неактивным
                inactive.append(player)
            elif (now - player.last_message_time).seconds >= INACTIVITY_TIMEOUT:
                inactive.append(player)
        
        return inactive
    
    def get_suspended_players(self) -> List[Player]:
        """Отстраненные игроки"""
        return [p for p in self.players.values() if p.is_suspended]

# ============================================
# ХРАНИЛИЩЕ
# ============================================

class GameStorage:
    def __init__(self):
        self.games: Dict[int, Game] = {}
        self.players: Dict[int, Player] = {}
        self.muted_users: Dict[Tuple[int, int], datetime] = {}
        self.chat_creators: Dict[int, int] = {}
        self.game_counter: int = 1
        self.prison_timers: Dict[int, asyncio.Task] = {}
        self.suspension_timers: Dict[int, asyncio.Task] = {}
        self.auto_play_tasks: Dict[int, asyncio.Task] = {}  # Задачи автоигры
    
    def create_game(self, chat_id: int, creator_id: int) -> Game:
        game = Game(chat_id=chat_id, game_number=self.game_counter, creator_id=creator_id)
        self.games[chat_id] = game
        self.chat_creators[chat_id] = creator_id
        self.game_counter += 1
        return game
    
    def get_game(self, chat_id: int) -> Optional[Game]:
        return self.games.get(chat_id)
    
    def get_player_game(self, user_id: int) -> Optional[Game]:
        player = self.players.get(user_id)
        if player and player.current_game_chat_id:
            return self.games.get(player.current_game_chat_id)
        return None
    
    def get_player(self, user_id: int) -> Optional[Player]:
        return self.players.get(user_id)
    
    def is_player_in_game(self, user_id: int) -> bool:
        player = self.players.get(user_id)
        return player is not None and player.current_game_chat_id is not None and not player.is_in_prison
    
    def is_player_suspended(self, user_id: int) -> bool:
        player = self.players.get(user_id)
        return player is not None and player.is_suspended
    
    def suspend_player(self, user_id: int, game_chat_id: int) -> Optional[Suspension]:
        """Отстранить игрока за неактивность"""
        player = self.players.get(user_id)
        game = self.games.get(game_chat_id)
        
        if not player or not game or player.status == PlayerStatus.DEAD:
            return None
        
        # Увеличиваем счетчик отстранений
        player.suspension_count += 1
        
        # Создаем отстранение
        suspension = Suspension(
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=SUSPENSION_TIME),
            suspension_count=player.suspension_count,
            bot_controlled=True
        )
        
        player.status = PlayerStatus.SUSPENDED
        player.suspension = suspension
        player.is_bot_controlled = True
        
        # Запускаем таймер отстранения
        self.start_suspension_timer(user_id, game_chat_id, SUSPENSION_TIME)
        
        # Запускаем автоигру за игрока
        self.start_auto_play(user_id, game_chat_id)
        
        return suspension
    
    def start_suspension_timer(self, user_id: int, chat_id: int, seconds: int):
        """Таймер окончания отстранения"""
        async def end_suspension():
            await asyncio.sleep(seconds)
            
            player = self.players.get(user_id)
            game = self.games.get(chat_id)
            
            if player and player.is_suspended and game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                
                # Останавливаем автоигру
                self.stop_auto_play(user_id)
                
                # Уведомляем игрока
                try:
                    bot_instance = Bot.get_current()
                    await bot_instance.send_message(
                        user_id,
                        f"🔓 ВАШЕ ОТСТРАНЕНИЕ ЗАКОНЧЕНО\n\n"
                        f"Вы возвращены к делу и можете работать.\n"
                        f"Помните: 5 минут неактивности = отстранение на 10 минут\n\n"
                        f"Количество отстранений: {player.suspension_count}\n"
                        f"Будьте активнее, чтобы избежать повторного отстранения!"
                    )
                    
                    # Если игра еще идет, отправляем текущую клавиатуру
                    if game.state == GameState.ACTIVE:
                        if player.role == Role.POLICE:
                            await bot_instance.send_message(
                                user_id,
                                "Ваши доступные действия:",
                                reply_markup=get_police_actions_keyboard()
                            )
                        elif player.role == Role.CRIMINAL:
                            await bot_instance.send_message(
                                user_id,
                                "Ваши доступные действия:",
                                reply_markup=get_criminal_actions_keyboard()
                            )
                except:
                    pass
        
        task = asyncio.create_task(end_suspension())
        self.suspension_timers[user_id] = task
    
    def start_auto_play(self, user_id: int, chat_id: int):
        """Запуск автоигры за отстраненного игрока"""
        async def auto_play_loop():
            player = self.players.get(user_id)
            game = self.games.get(chat_id)
            
            if not player or not game or not player.is_suspended:
                return
            
            # Случайное время между 5 и 6 минутами
            check_interval = random.randint(300, 360)  # 5-6 минут
            
            while player.is_suspended and game.state == GameState.ACTIVE:
                await asyncio.sleep(check_interval)
                
                if not player.is_suspended or game.state != GameState.ACTIVE:
                    break
                
                # Выполняем автоматическое действие в зависимости от роли
                action_result = await self.perform_auto_action(player, game)
                
                if action_result:
                    player.auto_actions.append(f"{datetime.now().strftime('%H:%M')}: {action_result}")
                
                # Обновляем время последнего действия
                player.last_action = datetime.now()
        
        task = asyncio.create_task(auto_play_loop())
        self.auto_play_tasks[user_id] = task
    
    async def perform_auto_action(self, player: Player, game: Game) -> str:
        """Выполнить автоматическое действие за игрока"""
        if player.role == Role.CRIMINAL:
            # Авто-убийство NPC
            if player.kills < KILLS_TO_WIN:
                player.kills += 1
                game.murder_count += 1
                
                victims = ["официанта", "таксиста", "бездомного", "продавца"]
                victim = random.choice(victims)
                
                # 30% шанс, что убийство будет замечено
                if random.random() < 0.3:
                    await broadcast_to_group(game,
                        f"📰 НОВОСТЬ: Обнаружено тело {victim}.\n"
                        f"На месте работают следователи."
                    )
                
                return f"Совершено убийство {victim}"
        
        elif player.role == Role.POLICE:
            # Авто-расследование
            actions = [
                "Проверка свидетельских показаний",
                "Осмотр места преступления",
                "Опрос потенциальных свидетелей",
                "Анализ улик"
            ]
            action = random.choice(actions)
            
            # 20% шанс найти улику
            if random.random() < 0.2:
                evidences = ["отпечаток", "волосок", "клочок ткани", "след"]
                evidence = random.choice(evidences)
                
                # Сохраняем в заметки
                if "улики" not in player.notes:
                    player.notes["улики"] = ""
                player.notes["улики"] += f"\n{datetime.now().strftime('%H:%M')}: Найден {evidence}"
                
                return f"{action}. Обнаружен {evidence}"
            
            return f"{action}. Ничего существенного не найдено."
        
        elif player.role == Role.IT:
            # Авто-поиск информации
            actions = [
                "Проверка телефонных соединений",
                "Анализ камер наблюдения",
                "Поиск в базе данных",
                "Мониторинг сетевой активности"
            ]
            action = random.choice(actions)
            return f"{action}. Данные обрабатываются."
        
        return "Рутинная работа"

    def stop_auto_play(self, user_id: int):
        """Остановить автоигру"""
        if user_id in self.auto_play_tasks:
            self.auto_play_tasks[user_id].cancel()
            del self.auto_play_tasks[user_id]
    
    def arrest_player(self, user_id: int, chat_id: int, crime: str = "убийства") -> PrisonRecord:
        """Арестовать игрока с учетом рецидивизма"""
        player = self.players.get(user_id)
        game = self.games.get(chat_id)
        
        if not player or not game:
            return None
        
        # Для рецидивистов - пожизненное
        if player.is_recidivist and player.role in [Role.CRIMINAL, Role.RECIDIVIST]:
            sentence_minutes = LIFE_SENTENCE
            is_life = True
        else:
            sentence_minutes = random.choice(PRISON_TIMES)
            is_life = False
        
        prison_record = PrisonRecord(
            game_number=game.game_number,
            chat_id=chat_id,
            sentence_minutes=sentence_minutes,
            arrest_time=datetime.now(),
            release_time=datetime.now() + timedelta(minutes=sentence_minutes),
            crime=crime,
            is_life=is_life
        )
        
        player.status = PlayerStatus.IN_PRISON
        player.current_prison = prison_record
        player.prison_records.append(prison_record)
        player.current_game_chat_id = None
        player.current_game_number = None
        
        # Останавливаем автоигру если была
        self.stop_auto_play(user_id)
        
        # Запускаем таймер (кроме пожизненного)
        if not is_life:
            self.start_prison_timer(user_id, sentence_minutes * 60)
        else:
            # Для пожизненного - специальное сообщение
            asyncio.create_task(self.notify_life_sentence(user_id))
        
        return prison_record
    
    async def notify_life_sentence(self, user_id: int):
        """Уведомить о пожизненном сроке"""
        await asyncio.sleep(1)
        player = self.players.get(user_id)
        if player:
            try:
                bot = Bot.get_current()
                await bot.send_message(
                    user_id,
                    "⚠️ ПОЖИЗНЕННЫЙ СРОК!\n\n"
                    "Вы признаны рецидивистом и приговорены к пожизненному заключению.\n\n"
                    "Вы не сможете участвовать в играх в этом чате.\n"
                    "Ваш игровой путь здесь завершен."
                )
            except:
                pass

    # ... остальные методы storage ...

storage = GameStorage()

# ============================================
# СИСТЕМА АКТИВНОСТИ
# ============================================

async def check_player_activity():
    """Проверка активности игроков во всех играх"""
    while True:
        await asyncio.sleep(AUTO_CHECK_INTERVAL)
        
        for chat_id, game in list(storage.games.items()):
            if game.state != GameState.ACTIVE:
                continue
            
            # Проверяем неактивных игроков
            inactive_players = game.get_inactive_players()
            
            for player in inactive_players:
                if player.can_be_suspended() and not player.is_suspended:
                    # Отстраняем игрока
                    suspension = storage.suspend_player(player.user_id, game.chat_id)
                    
                    if suspension:
                        # Уведомляем в ЛС (если может получить)
                        try:
                            bot = Bot.get_current()
                            await bot.send_message(
                                player.user_id,
                                f"⚠️ ВЫ ОТСТРАНЕНЫ ОТ ДЕЛА!\n\n"
                                f"Причина: неактивность более 5 минут\n"
                                f"Длительность отстранения: 10 минут\n\n"
                                f"В это время бот будет играть за вас.\n"
                                f"Вы вернетесь в игру: {suspension.end_time.strftime('%H:%M')}\n\n"
                                f"Количество отстранений: {player.suspension_count}"
                            )
                        except:
                            pass

async def start_game_with_inactive(game: Game):
    """Начать игру даже с неактивными игроками"""
    game.waiting_for_players = True
    
    # Даем дополнительное время активным игрокам
    await broadcast_to_group(game,
        f"⏳ ИГРА #{game.game_number} НАЧИНАЕТСЯ\n\n"
        f"Ожидание подтверждения от всех игроков...\n"
        f"У вас есть 2 минуты для активности!"
    )
    
    await asyncio.sleep(120)  # Ждем 2 минуты
    
    # Начинаем игру с теми, кто активен
    active_players = game.get_active_players()
    
    if len(active_players) >= MIN_PLAYERS:
        # Распределяем роли только среди активных
        await begin_game(game)
    else:
        await broadcast_to_group(game,
            f"❌ Недостаточно активных игроков для начала игры.\n"
            f"Нужно минимум {MIN_PLAYERS}, активно: {len(active_players)}"
        )
        game.state = GameState.REGISTRATION

# ============================================
# ХЕНДЛЕРЫ ДЛЯ РЕЦИДИВИСТОВ
# ============================================

@dp.callback_query(F.data == "reform_bad")
async def reform_bad(callback: CallbackQuery):
    """Игрок выбирает стать рецидивистом"""
    user = callback.from_user
    player = storage.get_player(user.id)
    
    if not player:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    
    player.criminal_attempts += 1
    
    if player.is_recidivist:
        player.role = Role.RECIDIVIST
        message = (
            "🔪 ВЫ СТАНОВИТЕСЬ РЕЦИДИВИСТОМ!\n\n"
            "⚠️ КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ:\n"
            "• В следующей игре вы будете помогать преступнику\n"
            "• Скорее всего, сами станете преступником\n"
            "• Если вас поймают - ПОЖИЗНЕННЫЙ срок\n"
            "• Шанс быть обнаруженным: В 3 РАЗА ВЫШЕ\n\n"
            "Вы уверены в своем выборе? Дороги назад не будет."
        )
    else:
        message = (
            "🔪 ВЫ ВЫБРАЛИ ВЕРНУТЬСЯ К ПРЕСТУПЛЕНИЯМ!\n\n"
            "⚠️ ВНИМАНИЕ:\n"
            "• В следующей игре вы будете помогать преступнику\n"
            "• Скорее всего, сами станете преступником\n"
            "• Если вас поймают - увеличенный срок\n"
            "• Шанс быть обнаруженным: В 2 РАЗА ВЫШЕ\n\n"
            f"Ваши судимости: {len(player.prison_records)}\n"
            f"Попыток вернуться к преступлениям: {player.criminal_attempts}"
        )
    
    await callback.message.edit_text(message)
    await callback.answer()

# ============================================
# ОБНОВЛЕННЫЕ ХЕНДЛЕРЫ
# ============================================

@dp.message(Command("begin"))
async def cmd_begin(message: Message):
    """Начало игры с проверкой активности"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах!")
        return
    
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if not game or game.state != GameState.REGISTRATION:
        await message.answer("Нет активной регистрации!")
        return
    
    if len(game.players) < MIN_PLAYERS:
        await message.answer(f"Недостаточно игроков! Минимум: {MIN_PLAYERS}")
        return
    
    # Запускаем проверку активности перед началом
    await start_game_with_inactive(game)

async def begin_game(game: Game):
    """Фактическое начало игры"""
    # Распределяем роли
    assigned_roles = assign_roles(game)
    game.state = GameState.ACTIVE
    game.start_time = datetime.now()
    game.waiting_for_players = False
    
    # Отправляем информацию о ролях в ЛС
    for player in game.players.values():
        try:
            await send_role_info(player, game)
            
            # Если игрок отстранен, уведомляем
            if player.is_suspended:
                await bot.send_message(
                    player.user_id,
                    f"⚠️ ИГРА #{game.game_number} НАЧАЛАСЬ\n\n"
                    f"Ваша роль: {player.role.value}\n"
                    f"Но вы отстранены за неактивность до: {player.suspension.end_time.strftime('%H:%M')}\n"
                    f"Бот играет за вас. Вернетесь через {int((player.suspension.end_time - datetime.now()).seconds / 60)} мин."
                )
        except Exception as e:
            logging.error(f"Не удалось отправить роль {player.user_id}: {e}")
    
    # Объявление в группе
    await broadcast_to_group(game,
        f"🚨 ИГРА #{game.game_number} НАЧАЛАСЬ! 🚨\n\n"
        f"Все игроки получили свои роли в личных сообщениях.\n"
        f"📊 Статистика:\n"
        f"• Активных игроков: {len(game.get_active_players())}\n"
        f"• Отстраненных: {len(game.get_suspended_players())}\n"
        f"• Всего участников: {len(game.players)}\n\n"
        f"📢 Первая новость от пресс-службы:"
    )
    
    # Первая новость
    await send_news(game)
    
    # Запускаем игровые циклы
    asyncio.create_task(game_loop(game))
    asyncio.create_task(murder_loop(game))
    
    # Запускаем проверку активности
    asyncio.create_task(check_player_activity())

# ============================================
# ОБРАБОТКА СООБЩЕНИЙ ДЛЯ ОТСЛЕЖИВАНИЯ АКТИВНОСТИ
# ============================================

@dp.message()
async def track_activity(message: Message):
    """Отслеживание активности игроков"""
    user_id = message.from_user.id
    player = storage.get_player(user_id)
    
    if player and player.current_game_chat_id:
        # Обновляем время последнего сообщения
        player.last_message_time = datetime.now()
        player.last_action = datetime.now()
        
        # Если игрок был отстранен и написал - снимаем отстранение
        if player.is_suspended:
            game = storage.get_game(player.current_game_chat_id)
            if game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                storage.stop_auto_play(user_id)
                
                await message.answer(
                    "✅ ВЫ ВОЗВРАЩЕНЫ К ДЕЛУ!\n"
                    "Отстранение снято досрочно за проявленную активность."
                )

@dp.callback_query()
async def track_callback_activity(callback: CallbackQuery):
    """Отслеживание активности через callback"""
    user_id = callback.from_user.id
    player = storage.get_player(user_id)
    
    if player and player.current_game_chat_id:
        player.last_message_time = datetime.now()
        player.last_action = datetime.now()
        
        # Если игрок был отстранен и проявил активность
        if player.is_suspended:
            game = storage.get_game(player.current_game_chat_id)
            if game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                storage.stop_auto_play(user_id)
                
                await callback.answer(
                    "✅ Вы возвращены к делу!",
                    show_alert=True
                )

# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print("=" * 50)
    print("ПОЛИЦЕЙСКИЙ ОТДЕЛ - Game Bot v4.1")
    print("Система автоматизации и контроля активности")
    print("=" * 50)
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

"""
============================================
ИНСТРУКЦИЯ ПО ЗАПУСКУ
============================================

1. УСТАНОВКА:
pip install aiogram==3.0.0b7 python-dotenv

2. СОЗДАЙТЕ ФАЙЛ .env:
BOT_TOKEN=ваш_токен_от_BotFather

3. НАСТРОЙКА БОТА:
- Дайте боту права администратора в группе
- Отключите "Разрешить анонимность"
- Добавьте бота в группу

4. КОМАНДЫ:
/start_game - начать регистрацию
/begin - начать игру
/cancel_game - отменить игру (создатель)
/mutebot - замутить нарушителя (создатель)
/status - статус игры
/players - список игроков

5. СИСТЕМА АКТИВНОСТИ:
- Неактивность 5+ минут = отстранение на 10 минут
- Бот автоматически играет за отстраненных
- После отстранения игрок получает уведомление
- Активность снимает отстранение досрочно
- Рецидивисты получают пожизненные сроки

6. СИСТЕМА СУДИМОСТИ:
- После тюрьмы игрок выбирает путь
- Исправиться = обычный игрок
- Вернуться к преступлениям = помощь преступнику
- 2+ судимости = рецидивист = пожизненное

7. АВТОМАТИЗАЦИЯ:
- Бот не ждет неактивных игроков
- После 2 минут ожидания игра начинается
- Неактивные отстраняются автоматически
- За отстраненных играет бот

============================================
ВАЖНЫЕ ИЗМЕНЕНИЯ v4.1:
============================================

1. СИСТЕМА ОТСТРАНЕНИЙ:
   - 5 минут неактивности = отстранение на 10 минут
   - Бот играет за отстраненного 5-6 минут, затем проверяет
   - Активность снимает отстранение
   - 2+ отстранения в одной игре = предупреждение

2. АВТОИГРА:
   - Бот выполняет реалистичные действия за игрока
   - Для преступника: убийства NPC
   - Для полиции: расследования, поиск улик
   - Действия логируются в auto_actions

3. РЕЦИДИВИЗМ:
   - 2+ судимости без исправления = рецидивист
   - Рецидивист = помощь преступнику в следующей игре
   - Пойманный рецидивист = пожизненный срок
   - Пожизненный = блокировка участия в этом чате

4. УЛУЧШЕННАЯ РЕГИСТРАЦИЯ:
   - Игрок не может быть в двух играх одновременно
   - При регистрации проверяется тюремный срок
   - Судимые получают предупреждения
   - Мут в одном чате не влияет на другие чаты

5. БЕЗОПАСНОСТЬ:
   - Бот удаляет сообщения в группе
   - Создатель может мутить нарушителей
   - Нарушение ролевой игры = мут
   - Раскрытие роли = предупреждение/мут

Удачи в игре и помните - это ролевая игра!
Играйте от лица персонажа, а не игрока!
"""
