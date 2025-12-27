ᯤ̸ ه𝑉𝐴𝑁𝐸𝑍ه, [27.12.2025 19:42]
#!/usr/bin/env python3
"""
🎄 PULS | Новогодний Чат-Менеджер 🎅
"""

import asyncio
import logging
import aiosqlite
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart

# Токен бота
TOKEN = "8514866233:AAGYy6DNaeiMM5XYICHH_kBfbLpHHOCaTFc"

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

# Создаем бота и диспетчер
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect('puls_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            nickname TEXT,
            description TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.commit()
        logger.info("✅ База данных инициализирована")

async def get_or_create_user(user_id: int, username: str = None, first_name: str = None):
    """Получить или создать пользователя в базе данных"""
    async with aiosqlite.connect('puls_bot.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_data = await cursor.fetchone()
        
        if not user_data:
            logger.info(f"🆕 Создаю нового пользователя: {user_id} - {first_name}")
            await db.execute(
                """INSERT INTO users (user_id, username, first_name, registered_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (user_id, username, first_name)
            )
            await db.commit()
        else:
            # Обновляем данные пользователя, если они изменились
            if username and user_data['username'] != username:
                logger.info(f"🔄 Обновляю username для {user_id}: {user_data['username']} -> {username}")
                await db.execute(
                    "UPDATE users SET username = ? WHERE user_id = ?",
                    (username, user_id)
                )
            if first_name and user_data['first_name'] != first_name:
                logger.info(f"🔄 Обновляю first_name для {user_id}: {user_data['first_name']} -> {first_name}")
                await db.execute(
                    "UPDATE users SET first_name = ? WHERE user_id = ?",
                    (first_name, user_id)
                )
            await db.commit()
        
        # Получаем обновленные данные
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_data = await cursor.fetchone()
        
        return dict(user_data) if user_data else None

async def set_user_description(user_id: int, description: str):
    """Установить описание пользователю"""
    try:
        async with aiosqlite.connect('puls_bot.db') as db:
            # Проверяем, существует ли пользователь
            cursor = await db.execute(
                "SELECT 1 FROM users WHERE user_id = ?",
                (user_id,)
            )
            exists = await cursor.fetchone()
            
            if not exists:
                logger.error(f"❌ Пользователь {user_id} не найден в базе!")
                return False
            
            # Обновляем описание
            await db.execute(
                "UPDATE users SET description = ? WHERE user_id = ?",
                (description, user_id)
            )
            await db.commit()
            
            # Проверяем, обновилось ли
            cursor = await db.execute(
                "SELECT description FROM users WHERE user_id = ?",

ᯤ̸ ه𝑉𝐴𝑁𝐸𝑍ه, [27.12.2025 19:42]
(user_id,)
            )
            updated = await cursor.fetchone()
            
            if updated and updated[0] == description:
                logger.info(f"✅ Описание для {user_id} успешно сохранено: '{description}'")
                return True
            else:
                logger.error(f"❌ Описание для {user_id} НЕ сохранено!")
                return False
                
    except Exception as e:
        logger.error(f"🔥 Ошибка при сохранении описания: {e}")
        return False

async def get_user_profile(user_id: int):
    """Получить полный профиль пользователя"""
    async with aiosqlite.connect('puls_bot.db') as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_data = await cursor.fetchone()
        
        if user_data:
            user_dict = dict(user_data)
            logger.info(f"📊 Профиль {user_id}: description='{user_dict.get('description')}'")
            return user_dict
        else:
            logger.info(f"📭 Пользователь {user_id} не найден в базе")
            return None

# ==================== КОМАНДА /START ====================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработка команды /start"""
    user = message.from_user
    await get_or_create_user(user.id, user.username, user.first_name)
    
    welcome_text = f"""
🎄 <b>Добро пожаловать в PULS, {user.first_name}!</b>

✨ <b>Проверьте работу команд:</b>

1️⃣ <b>Установить описание:</b>
<code>оп Я люблю Новый год!</code>

2️⃣ <b>Посмотреть описание:</b>
Ответьте на сообщение: <code>опл</code>

3️⃣ <b>Проверить бота:</b>
<code>пульс</code>

4️⃣ <b>Свой профиль:</b>
<code>кт</code>

🚀 <b>Начните с команды оп!</b>
    """
    
    await message.answer(welcome_text)
    logger.info(f"🚀 Пользователь {user.id} использовал /start")

# ==================== КОМАНДА "ОП" (БЕЗ ТОЧКИ) ====================
@dp.message(F.text.casefold().startswith("оп "))
async def cmd_set_description(message: types.Message):
    """Установить описание пользователя"""
    user = message.from_user
    
    # Получаем текст после "оп "
    text = message.text.strip()
    
    if len(text) <= 3:
        await message.reply("❌ <b>Ошибка!</b> Напишите текст после 'оп'\n\nПример: <code>оп Я люблю Новый год!</code>")
        return
    
    description = text[3:].strip()  # Убираем "оп "
    
    if len(description) > 100:
        await message.reply("❌ <b>Слишком длинно!</b> Максимум 100 символов")
        return
    
    if len(description) < 2:
        await message.reply("❌ <b>Слишком коротко!</b> Нужно минимум 2 символа")
        return
    
    logger.info(f"📝 Пытаюсь сохранить описание для {user.id}: '{description}'")
    
    try:
        # Создаем/обновляем пользователя в базе
        await get_or_create_user(user.id, user.username, user.first_name)
        
        # Сохраняем описание
        success = await set_user_description(user.id, description)
        
        if success:
            # Показываем подтверждение
            await message.reply(
                f"✅ <b>Описание успешно установлено!</b>\n\n"
                f"📝 <b>Ваше описание:</b>\n"
                f"{description}\n\n"
                f"✨ Теперь другие могут увидеть его командой <code>опл</code>\n"
                f"🆔 Ваш ID: <code>{user.id}</code>"
            )
            logger.info(f"🎉 Описание сохранено для {user.id}")
        else:
            await message.reply(
                f"❌ <b>Ошибка при сохранении!</b>\n"
                f"Попробуйте еще раз.\n\n"
                f"Пример: <code>оп Ваш текст</code>"
            )
            logger.error(f"💥 Не удалось сохранить описание для {user.id}")
            
    except Exception as e:
        logger.error(f"🔥 Критическая ошибка в команде 'оп': {e}")
        await message.reply("❌ <b>Ошибка сервера!</b> Попробуйте позже.")

ᯤ̸ ه𝑉𝐴𝑁𝐸𝑍ه, [27.12.2025 19:42]
# ==================== КОМАНДА "ОПЛ" (БЕЗ ТОЧКИ) ====================
@dp.message(F.text.casefold() == "опл")
async def cmd_show_description(message: types.Message):
    """Показать описание пользователя"""
    logger.info(f"👁‍🗨 Команда 'опл' от {message.from_user.id}")
    
    if not message.reply_to_message:
        await message.reply(
            "⚠️ <b>Ответьте на сообщение пользователя!</b>\n\n"
            "<b>Как использовать:</b>\n"
            "1. Найдите сообщение пользователя\n"
            "2. Нажмите «Ответить»\n"
            "3. Напишите: <code>опл</code>\n"
            "4. Отправьте сообщение"
        )
        return
    
    target_user = message.reply_to_message.from_user
    logger.info(f"🔍 Ищу описание для {target_user.id} ({target_user.first_name})")
    
    try:
        # Получаем профиль пользователя
        profile = await get_user_profile(target_user.id)
        
        if profile:
            logger.info(f"📋 Профиль найден: {profile}")
            
            if profile.get('description'):
                description = profile['description']
                await message.reply(
                    f"📝 <b>Описание {target_user.first_name}:</b>\n\n"
                    f"✨ {description}\n\n"
                    f"🆔 ID: <code>{target_user.id}</code>"
                )
                logger.info(f"✅ Показано описание для {target_user.id}: '{description}'")
            else:
                await message.reply(
                    f"ℹ️ <b>У {target_user.first_name} нет описания</b>\n\n"
                    f"<b>Чтобы установить описание:</b>\n"
                    f"<code>оп ваш_текст</code>\n\n"
                    f"🆔 ID: <code>{target_user.id}</code>"
                )
                logger.info(f"ℹ️ У {target_user.id} нет описания в базе")
        else:
            # Если пользователя нет в базе
            await message.reply(
                f"ℹ️ <b>У {target_user.first_name} нет описания</b>\n\n"
                f"<b>Чтобы установить описание:</b>\n"
                f"<code>оп ваш_текст</code>\n\n"
                f"🆔 ID: <code>{target_user.id}</code>"
            )
            logger.info(f"ℹ️ Пользователь {target_user.id} не найден в базе")
            
    except Exception as e:
        logger.error(f"🔥 Ошибка в команде 'опл': {e}")
        await message.reply("❌ <b>Ошибка при получении данных!</b>")

# ==================== КОМАНДА "ПУЛЬС" ====================
@dp.message(F.text.casefold() == "пульс")
async def cmd_puls(message: types.Message):
    """Проверка работоспособности бота"""
    user = message.from_user
    logger.info(f"💓 Команда 'пульс' от {user.id}")
    
    responses = [
        f"✅ <b>Бот работает!</b>\n👤 Пользователь: {user.first_name}\n🆔 ID: <code>{user.id}</code>",
        f"🎄 <b>На связи!</b>\nВсе системы в норме!\n👤 {user.first_name}\n🆔 <code>{user.id}</code>",
        f"✨ <b>Работаю!</b>\nГотов к действиям!\n👤 {user.first_name}\n🆔 <code>{user.id}</code>",
    ]
    
    response = random.choice(responses)
    await message.reply(response)
    logger.info(f"📤 Отправлен ответ на 'пульс' для {user.id}")

# ==================== КОМАНДА "КТ" (БЕЗ ТОЧКИ) ====================
@dp.message(F.text.casefold() == "кт")
async def cmd_my_profile(message: types.Message):
    """Показать свой профиль"""
    user = message.from_user
    logger.info(f"👤 Команда 'кт' от {user.id}")
    
    try:
        # Получаем или создаем профиль
        profile = await get_or_create_user(user.id, user.username, user.first_name)
        
        if profile:
            description = profile.get('description', 'Не указано')
            
            profile_text = f"""
👤 <b>{user.first_name}</b>
🆔 ID: <code>{user.id}</code>

📝 <b>Описание:</b>
{description if description != 'Не указано' else '❌ Не указано'}

✨ <b>Чтобы установить/изменить описание:</b>
<code>оп ваш_текст</code>

ᯤ̸ ه𝑉𝐴𝑁𝐸𝑍ه, [27.12.2025 19:42]
🔍 <b>Чтобы посмотреть описание другого:</b>
Ответьте на сообщение: <code>опл</code>
            """
        else:
            profile_text = f"""
👤 <b>{user.first_name}</b>
🆔 ID: <code>{user.id}</code>

📝 <b>Описание:</b>
❌ Не указано

✨ <b>Чтобы установить описание:</b>
<code>оп ваш_текст</code>
            """
        
        await message.reply(profile_text)
        logger.info(f"✅ Показан профиль для {user.id}")
        
    except Exception as e:
        logger.error(f"🔥 Ошибка в команде 'кт': {e}")
        await message.reply("❌ <b>Ошибка при получении профиля!</b>")

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Запуск бота"""
    print("=" * 50)
    print("🎄 ЗАПУСК БОТА PULS 🎄")
    print("=" * 50)
    
    logger.info("=" * 50)
    logger.info("🎄 ЗАПУСК БОТА PULS 🎄")
    logger.info("=" * 50)
    
    # Инициализация базы данных
    logger.info("💾 Инициализация базы данных...")
    await init_db()
    
    logger.info("✅ База данных готова")
    logger.info("🚀 Запуск polling...")
    print("🚀 Бот запущен! Ожидаю команды...")
    print("📝 Попробуйте команды: оп, опл, пульс, кт")
    
    # Запускаем бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"🔥 Ошибка при запуске бота: {e}")
        print(f"🔥 Ошибка: {e}")
    finally:
        await bot.session.close()
        logger.info("🛑 Бот остановлен")
        print("🛑 Бот остановлен")

if name == "main":

    asyncio.run(main())
