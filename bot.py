import os
import logging
import re
from datetime import datetime
from typing import Optional, Dict, List

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

from database import Database
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройки
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = os.getenv('WEB_APP_URL', 'https://ваш-проект.railway.app')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
db = Database()

# ========== СОСТОЯНИЯ (FSM) ==========
class ReputationStates(StatesGroup):
    waiting_for_reputation = State()
    waiting_for_search = State()
    viewing_reputation = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_profile(user_data: Dict, stats: Dict) -> str:
    """Форматирование профиля пользователя"""
    username = f"@{user_data['username']}" if user_data['username'] else "Без username"
    
    # Форматирование даты
    created_at = datetime.strptime(user_data['created_at'], '%Y-%m-%d %H:%M:%S')
    date_str = created_at.strftime('%d %B %Y').replace('January', 'января').replace('February', 'февраля')\
        .replace('March', 'марта').replace('April', 'апреля').replace('May', 'мая')\
        .replace('June', 'июня').replace('July', 'июля').replace('August', 'августа')\
        .replace('September', 'сентября').replace('October', 'октября')\
        .replace('November', 'ноября').replace('December', 'декабря')
    
    profile_text = f"""<blockquote>{username} (ID: {user_data['user_id']})

{stats['total']} шт. · {stats['positive_percent']}% положительных · {stats['negative_percent']}% отрицательных

0 шт. · 0 RUB сумма сделок

Зарегистрирован
{date_str}</blockquote>"""
    
    return profile_text

def get_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Главная клавиатура"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(
        types.KeyboardButton("Отправить репутацию"),
        types.KeyboardButton("Скопировать ID"),
        types.KeyboardButton("Поиск user"),
        types.KeyboardButton("Профиль")
    )
    return keyboard

def get_back_keyboard() -> types.ReplyKeyboardMarkup:
    """Клавиатура с кнопкой Назад"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

def get_profile_keyboard(is_own_profile: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для профиля"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if is_own_profile:
        keyboard.add(
            InlineKeyboardButton("🏆 Моя репа", callback_data="my_reputation"),
            InlineKeyboardButton("🗒️ Скопировать ID", callback_data="copy_id")
        )
    else:
        keyboard.add(InlineKeyboardButton("Посмотреть репутацию", callback_data="view_reputation"))
    
    keyboard.add(InlineKeyboardButton("↩️ Назад", callback_data="back_to_main"))
    return keyboard

def get_reputation_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа репутации"""
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("Все", callback_data="rep_all"),
        InlineKeyboardButton("Положительные", callback_data="rep_positive"),
        InlineKeyboardButton("Отрицательные", callback_data="rep_negative")
    )
    keyboard.add(InlineKeyboardButton("↩️ Назад", callback_data="back_to_profile"))
    return keyboard

def get_reputation_navigation_keyboard(current_index: int, total: int, rep_id: int) -> InlineKeyboardMarkup:
    """Клавиатура навигации по отзывам"""
    keyboard = InlineKeyboardMarkup(row_width=3)
    
    buttons = []
    if current_index > 0:
        buttons.append(InlineKeyboardButton("⬅️", callback_data=f"rep_prev_{rep_id}"))
    
    buttons.append(InlineKeyboardButton(f"{current_index + 1}/{total}", callback_data="noop"))
    
    if current_index < total - 1:
        buttons.append(InlineKeyboardButton("➡️", callback_data=f"rep_next_{rep_id}"))
    
    if buttons:
        keyboard.row(*buttons)
    
    keyboard.add(InlineKeyboardButton("↩️ Выйти", callback_data="back_to_rep_types"))
    return keyboard

def parse_reputation_command(text: str) -> Optional[tuple]:
    """Парсинг команды репутации"""
    patterns = [
        r'^([+-])(rep|реп)\s+(@?\w+|\d+)\s*(.*)$',
        r'^([+-])(rep|реп)\s+(@?\w+|\d+)$'
    ]
    
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            sign = match.group(1)  # + или -
            target = match.group(3).lstrip('@')  # username или ID
            comment = match.group(4) if match.group(4) else ""
            
            vote_type = 'positive' if sign == '+' else 'negative'
            return vote_type, target, comment
    
    return None

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    
    # Регистрируем/обновляем пользователя
    db.get_or_create_user(user_id, username, first_name, last_name)
    
    # Форматированный текст
    text = f"""Репутация — твоя гарантия безопасности.  
Ваш ID: [{user_id}]  

Здесь можно смотреть и сохранять репутацию, а при сомнениях — провести сделку через автогаранта."""
    
    await message.answer(text, reply_markup=get_main_keyboard())

@dp.message_handler(lambda message: message.text == "Отправить репутацию")
async def send_reputation_handler(message: types.Message):
    """Обработчик кнопки 'Отправить репутацию'"""
    text = """Отправьте репутацию.
К репутации необходимо приложить хотя бы одну фотографию.

Пример «+rep @username все супер».
Пример «-rep user_id все супер»."""
    
    await message.answer(text, reply_markup=get_back_keyboard())
    await ReputationStates.waiting_for_reputation.set()

@dp.message_handler(lambda message: message.text == "Скопировать ID")
async def copy_id_handler(message: types.Message):
    """Обработчик кнопки 'Скопировать ID'"""
    user_id = message.from_user.id
    
    # Создаем Web App кнопку
    web_app = types.WebAppInfo(url=f"{WEB_APP_URL}/web_app/copy_id.html?user_id={user_id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("📋 Скопировать ID", web_app=web_app))
    
    await message.answer("Нажмите кнопку ниже, чтобы скопировать ваш ID:", reply_markup=keyboard)

@dp.message_handler(lambda message: message.text == "Поиск user")
async def search_user_handler(message: types.Message):
    """Обработчик кнопки 'Поиск user'"""
    await message.answer(
        "🔎Отправьте username или ID пользователя,чей профиль хотите найти.",
        reply_markup=get_back_keyboard()
    )
    await ReputationStates.waiting_for_search.set()

@dp.message_handler(lambda message: message.text == "Профиль")
async def profile_handler(message: types.Message):
    """Обработчик кнопки 'Профиль'"""
    user_id = message.from_user.id
    
    # Получаем данные пользователя
    user_data = db.get_user(user_id)
    if not user_data:
        await message.answer("Ошибка: пользователь не найден.")
        return
    
    # Получаем статистику
    stats = db.get_user_stats(user_id)
    
    # Форматируем профиль
    profile_text = format_profile(user_data, stats)
    
    # Отправляем с кнопками
    await message.answer(
        profile_text,
        parse_mode='HTML',
        reply_markup=get_profile_keyboard(is_own_profile=True)
    )

@dp.message_handler(lambda message: message.text == "Назад", state="*")
async def back_handler(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Назад'"""
    await state.finish()
    await cmd_start(message)

# ========== ОБРАБОТКА РЕПУТАЦИИ ==========
@dp.message_handler(state=ReputationStates.waiting_for_reputation, content_types=['text', 'photo'])
async def process_reputation(message: types.Message, state: FSMContext):
    """Обработка отправки репутации"""
    user_id = message.from_user.id
    
    # Проверяем наличие фото
    has_photo = message.photo is not None and len(message.photo) > 0
    
    # Получаем текст (из сообщения или подписи к фото)
    text = message.caption if has_photo else message.text
    
    if not text:
        await message.answer("Пожалуйста, укажите команду репутации.")
        return
    
    # Парсим команду
    parsed = parse_reputation_command(text)
    if not parsed:
        await message.answer("Неверный формат команды. Используйте: +rep @username [комментарий]")
        return
    
    vote_type, target_query, comment = parsed
    
    # Ищем целевого пользователя
    target_user = db.search_user(target_query)
    if not target_user:
        await message.answer("❌ Пользователь не найден!")
        return
    
    # Проверяем наличие фото
    if not has_photo:
        await message.answer("Ваша репутация не принята! Необходимо приложить фотографию.")
        return
    
    # Получаем file_id фото (берем самое большое)
    photo_id = message.photo[-1].file_id
    
    # Добавляем репутацию в БД
    success, msg = db.add_reputation(
        from_user_id=user_id,
        to_user_id=target_user['user_id'],
        vote_type=vote_type,
        comment=comment,
        photo_id=photo_id
    )
    
    if success:
        await message.answer("Репутация сохранена✅")
        await state.finish()
        await cmd_start(message)
    else:
        await message.answer(f"Ошибка: {msg}")

# ========== ПОИСК ПОЛЬЗОВАТЕЛЯ ==========
@dp.message_handler(state=ReputationStates.waiting_for_search)
async def process_search(message: types.Message, state: FSMContext):
    """Обработка поиска пользователя"""
    query = message.text.strip()
    
    # Ищем пользователя
    target_user = db.search_user(query)
    if not target_user:
        await message.answer("❌Пользователь не найден!")
        return
    
    # Получаем статистику
    stats = db.get_user_stats(target_user['user_id'])
    
    # Форматируем профиль
    profile_text = format_profile(target_user, stats)
    
    # Сохраняем ID найденного пользователя в состоянии
    await state.update_data(found_user_id=target_user['user_id'])
    
    # Отправляем профиль с кнопками
    await message.answer(
        profile_text,
        parse_mode='HTML',
        reply_markup=get_profile_keyboard(is_own_profile=False)
    )

# ========== КОМАНДЫ В ЧАТАХ ==========
@dp.message_handler(commands=['и', 'i'])
async def public_profile_command(message: types.Message):
    """Команда /и или /i для публичного профиля"""
    # Проверяем, что это ответ на сообщение
    if not message.reply_to_message:
        await message.reply("Пожалуйста, ответьте этой командой на сообщение пользователя.")
        return
    
    target_user = message.reply_to_message.from_user
    
    # Получаем данные из БД
    user_data = db.get_or_create_user(
        target_user.id,
        target_user.username or "",
        target_user.first_name or "",
        target_user.last_name or ""
    )
    
    if not user_data:
        await message.reply("❌ Пользователь не найден!")
        return
    
    # Получаем статистику
    stats = db.get_user_stats(target_user.id)
    
    # Форматируем профиль (упрощенный, без кнопок в тексте)
    profile_text = format_profile(user_data, stats)
    
    # Создаем инлайн-кнопку "Перейти в профиль"
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            "Перейти в профиль", 
            url=f"https://t.me/{(await bot.me).username}?start=profile_{target_user.id}"
        )
    )
    
    await message.reply(profile_text, parse_mode='HTML', reply_markup=keyboard)

@dp.message_handler(lambda message: message.text and (
    message.text.startswith('+rep') or 
    message.text.startswith('-rep') or
    message.text.startswith('+реп') or 
    message.text.startswith('-реп')
))
async def public_reputation_handler(message: types.Message):
    """Обработка репутации в публичных чатах"""
    # Проверяем наличие фото
    has_photo = message.photo is not None and len(message.photo) > 0
    
    # Получаем текст
    text = message.caption if has_photo else message.text
    
    # Парсим команду
    parsed = parse_reputation_command(text)
    if not parsed:
        return  # Не реагируем на некорректный формат
    
    vote_type, target_query, comment = parsed
    
    # Ищем целевого пользователя
    target_user = db.search_user(target_query)
    if not target_user:
        await message.reply("❌ Пользователь не найден!")
        return
    
    # Проверяем наличие фото
    if not has_photo:
        await message.reply("Ваша репутация не принята! Необходимо приложить фотографию.")
        return
    
    # Получаем file_id фото
    photo_id = message.photo[-1].file_id if message.photo else ""
    
    # Добавляем репутацию
    success, msg = db.add_reputation(
        from_user_id=message.from_user.id,
        to_user_id=target_user['user_id'],
        vote_type=vote_type,
        comment=comment,
        photo_id=photo_id
    )
    
    if success:
        await message.reply("Репутация сохранена✅")
    else:
        await message.reply(f"Ошибка: {msg}")

# ========== ОБРАБОТКА CALLBACK-ЗАПРОСОВ ==========
@dp.callback_query_handler(lambda c: c.data == "my_reputation")
async def my_reputation_callback(callback_query: types.CallbackQuery):
    """Кнопка 'Моя репа'"""
    await callback_query.message.edit_text(
        "Выберите тип:",
        reply_markup=get_reputation_type_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data.startswith("rep_"))
async def reputation_filter_callback(callback_query: types.CallbackQuery):
    """Выбор типа репутации"""
    data = callback_query.data
    
    if data == "back_to_profile":
        # Возврат к профилю
        user_id = callback_query.from_user.id
        user_data = db.get_user(user_id)
        stats = db.get_user_stats(user_id)
        
        profile_text = format_profile(user_data, stats)
        
        await callback_query.message.edit_text(
            profile_text,
            parse_mode='HTML',
            reply_markup=get_profile_keyboard(is_own_profile=True)
        )
        return
    
    # Определяем тип фильтра
    filter_type = 'all'
    if data == "rep_positive":
        filter_type = 'positive'
    elif data == "rep_negative":
        filter_type = 'negative'
    
    # Получаем отзывы
    user_id = callback_query.from_user.id
    reputation_list = db.get_user_reputation(user_id, filter_type)
    
    if not reputation_list:
        await callback_query.answer("Нет отзывов выбранного типа", show_alert=True)
        return
    
    # Показываем первый отзыв
    await show_reputation_item(callback_query.message, reputation_list, 0, filter_type)

async def show_reputation_item(message: types.Message, rep_list: List[Dict], index: int, filter_type: str):
    """Показ одного отзыва"""
    if index < 0 or index >= len(rep_list):
        return
    
    rep = rep_list[index]
    
    # Формируем текст
    vote_emoji = "✅" if rep['vote_type'] == 'positive' else "❌"
    from_user = f"@{rep['username']}" if rep['username'] else f"ID: {rep['from_user_id']}"
    date = datetime.strptime(rep['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
    
    text = f"""{vote_emoji} <b>Отзыв {index + 1} из {len(rep_list)}</b>

От: {from_user}
Дата: {date}
Тип: {'Положительный' if rep['vote_type'] == 'positive' else 'Отрицательный'}
Комментарий: {rep['comment'] or 'Без комментария'}"""
    
    # Создаем клавиатуру навигации
    keyboard = get_reputation_navigation_keyboard(index, len(rep_list), rep['id'])
    
    # Отправляем фото с текстом
    await message.answer_photo(
        photo=rep['photo_id'],
        caption=text,
        parse_mode='HTML',
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith("rep_prev_") or c.data.startswith("rep_next_"))
async def reputation_navigation_callback(callback_query: types.CallbackQuery):
    """Навигация по отзывам"""
    data = callback_query.data
    
    # Определяем направление и ID текущего отзыва
    if data.startswith("rep_prev_"):
        direction = -1
        current_rep_id = int(data.split("_")[2])
    else:
        direction = 1
        current_rep_id = int(data.split("_")[2])
    
    # Получаем текущий отзыв
    current_rep = db.get_reputation_by_id(current_rep_id)
    if not current_rep:
        await callback_query.answer("Отзыв не найден", show_alert=True)
        return
    
    # Получаем все отзывы для этого пользователя
    user_id = current_rep['to_user_id']
    filter_type = 'all'  # Можно сохранять фильтр в состоянии
    
    rep_list = db.get_user_reputation(user_id, filter_type)
    
    # Находим текущий индекс
    current_index = next((i for i, r in enumerate(rep_list) if r['id'] == current_rep_id), -1)
    if current_index == -1:
        await callback_query.answer("Ошибка навигации", show_alert=True)
        return
    
    # Вычисляем новый индекс
    new_index = current_index + direction
    
    # Показываем новый отзыв
    await callback_query.message.delete()  # Удаляем старое сообщение
    await show_reputation_item(callback_query.message, rep_list, new_index, filter_type)

@dp.callback_query_handler(lambda c: c.data == "view_reputation")
async def view_reputation_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Кнопка 'Посмотреть репутацию' для чужого профиля"""
    state_data = await state.get_data()
    target_user_id = state_data.get('found_user_id')
    
    if not target_user_id:
        await callback_query.answer("Ошибка: пользователь не найден", show_alert=True)
        return
    
    # Сохраняем ID пользователя в состоянии
    await state.update_data(viewing_user_id=target_user_id)
    
    # Показываем выбор типа
    await callback_query.message.edit_text(
        "Выберите тип:",
        reply_markup=get_reputation_type_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "back_to_rep_types")
async def back_to_types_callback(callback_query: types.CallbackQuery):
    """Возврат к выбору типа репутации"""
    await callback_query.message.edit_text(
        "Выберите тип:",
        reply_markup=get_reputation_type_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "back_to_main")
async def back_to_main_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Возврат к главному меню"""
    await state.finish()
    await callback_query.message.delete()
    
    user_id = callback_query.from_user.id
    text = f"""Репутация — твоя гарантия безопасности.  
Ваш ID: [{user_id}]  

Здесь можно смотреть и сохранять репутацию, а при сомнениях — провести сделку через автогаранта."""
    
    await callback_query.message.answer(text, reply_markup=get_main_keyboard())

@dp.callback_query_handler(lambda c: c.data == "copy_id")
async def copy_id_callback(callback_query: types.CallbackQuery):
    """Кнопка 'Скопировать ID' в профиле"""
    user_id = callback_query.from_user.id
    
    # Создаем Web App кнопку
    web_app = types.WebAppInfo(url=f"{WEB_APP_URL}/web_app/copy_id.html?user_id={user_id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("📋 Скопировать ID", web_app=web_app))
    
    await callback_query.message.answer(
        "Нажмите кнопку ниже, чтобы скопировать ваш ID:",
        reply_markup=keyboard
    )
    await callback_query.answer()

# ========== СТАРТ БОТА ==========
async def on_startup(dp):
    """Действия при запуске бота"""
    logger.info("Бот запущен!")
    
    # Создаем таблицы в БД
    db.create_tables()
    
    # Устанавливаем команды бота
    commands = [
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("help", "Помощь")
    ]
    await bot.set_my_commands(commands)

async def on_shutdown(dp):
    """Действия при остановке бота"""
    logger.info("Бот останавливается...")
    db.close()
    await dp.storage.close()
    await dp.storage.wait_closed()

if __name__ == '__main__':
    executor.start_polling(
        dp, 
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )
