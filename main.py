from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaDocument
import logging
import sqlite3
import datetime
import subprocess, os
from datetime import timedelta
import asyncio
from zoneinfo import ZoneInfo
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent  # папка, где лежит main.py
VIDEO_DIR = BASE_DIR
FFMPEG_PATH = BASE_DIR
VIDEO_EXTS = ["*.mp4","*.MP4"]

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8385302636:AAHDgQF-rHDr__1Iov9v8iIixKI5vK8oeJ8"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Часовые пояса
MSK_TZ = ZoneInfo("Europe/Moscow")
UTC_TZ = ZoneInfo("UTC")

# Список разрешенных пользователей
ALLOWED_USERS = {
    "@burgerking312",
    "@veron144ka",
    "@DashaRyzhova",
    "@loreley1264",
    "@vaditmn",
    "@olikburlakova",
    "@milkenxxx",
    "@astratov_roman"

}

ADMIN_USERS = {"@burgerking312","@veron144ka",  "@DashaRyzhova"}

# Функция проверки админских прав
async def check_admin(username: str) -> bool:
    return username in ADMIN_USERS

# Фоновая задача для очистки старых событий
async def clean_old_events_task():
    logger.info("Запуск задачи очистки старых событий")
    while True:
        try:
            clean_old_events(days=1)  # Удаляем события старше 1 дня
        except Exception as e:
            logger.error(f"Ошибка в задаче очистки: {e}")
        await asyncio.sleep(86400)  # Запускаем раз в сутки (86400 секунд)


def get_allowed_users_chat_ids():
    """Получаем chat_id всех разрешенных пользователей из базы данных"""
    conn = sqlite3.connect('events.db')
    c = conn.cursor()

    # Создаем плейсхолдеры для IN-условия
    placeholders = ','.join(['?'] * len(ALLOWED_USERS))
    query = f"SELECT DISTINCT chat_id FROM users WHERE username IN ({placeholders})"

    c.execute(query, list(ALLOWED_USERS))
    chat_ids = [row[0] for row in c.fetchall()]
    conn.close()
    return chat_ids


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('events.db')
    c = conn.cursor()

    # Создаем таблицу событий с проверкой существующих колонок
    c.execute('''CREATE TABLE IF NOT EXISTS events
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 park TEXT NOT NULL,
                 event_date TEXT NOT NULL,
                 event_text TEXT NOT NULL,
                 remind_before INTEGER NOT NULL,
                 user_id TEXT NOT NULL,
                 chat_id INTEGER NOT NULL,
                 reminded INTEGER DEFAULT 0)''')

    # Проверяем наличие колонки comment
    c.execute("PRAGMA table_info(events)")
    columns = [column[1] for column in c.fetchall()]
    if 'comment' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN comment TEXT")
        logger.info("Добавлен новый столбец 'comment' в таблицу events")

    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT NOT NULL UNIQUE,
                 chat_id INTEGER NOT NULL)''')

    conn.commit()
    conn.close()


init_db()


class Form(StatesGroup):
    waiting_for_instructor = State()
    waiting_for_park = State()
    waiting_for_print = State()
    waiting_for_document = State()
    waiting_for_month = State()
    in_section = State()
    # Новые состояния для календаря
    waiting_for_event_date = State()
    waiting_for_event_text = State()
    waiting_for_remind_before = State()
    waiting_for_comment = State()  # Новое состояние для комментария
    waiting_for_event_to_delete = State()
    in_instructions = State()  # Новое состояние для раздела инструкций
    in_training = State()  # Новое состояние для обучения
    in_calendar = State()


async def send_compressed_video(message: types.Message, input_name: str, caption: str = None):
    input_path = VIDEO_DIR / input_name
    output_name = f"compressed_{input_name}"
    output_path = VIDEO_DIR / output_name

    try:
        # Проверяем размер исходного файла
        file_size_mb = input_path.stat().st_size / (1024 * 1024)
        logger.info(f"Размер файла {input_name}: {file_size_mb:.1f} МБ")

        # Если файл слишком большой - предупреждаем и отказываемся
        if file_size_mb > 100:  # Больше 100 МБ
            await message.answer(
                f"❌ Файл {input_name} слишком большой ({file_size_mb:.1f} МБ). Максимальный размер для обработки: 100 МБ.")
            return

        await message.answer("🔄 Идёт сжатие и отправка видео, пожалуйста, подождите…")

        if file_size_mb > 30:  # Для больших файлов (>30 МБ)
            await message.answer(
                f"📁 Обрабатывается большой файл ({file_size_mb:.1f} МБ), это может занять до 2-3 минут...")

        # Быстрые настройки сжатия для разных размеров
        if "Комус" in input_name or file_size_mb > 50:
            # Для Комус и больших файлов - быстрое агрессивное сжатие
            ffmpeg_command = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vcodec", "libx264",
                "-preset", "ultrafast",  # Самый быстрый пресет
                "-crf", "30",  # Более агрессивное сжатие
                "-vf", "scale=1280:720",  # Уменьшаем до 720p
                "-acodec", "aac", "-b:a", "64k",  # Низкий битрейт аудио
                "-movflags", "+faststart",  # Быстрый старт
                str(output_path)
            ]
            logger.info(f"Применяем быстрое сжатие для {input_name}")
        elif file_size_mb > 20:  # Средние файлы
            ffmpeg_command = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vcodec", "libx264",
                "-preset", "fast",
                "-crf", "28",
                "-acodec", "aac", "-b:a", "96k",
                str(output_path)
            ]
        else:  # Маленькие файлы
            ffmpeg_command = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vcodec", "libx264",
                "-preset", "medium",
                "-crf", "26",
                "-acodec", "aac", "-b:a", "96k",
                str(output_path)
            ]

        result = subprocess.run(ffmpeg_command)

        if result.returncode != 0:
            logger.error(f"Ошибка ffmpeg для файла: {input_name}")
            await message.answer(f"❌ Ошибка при сжатии видео: {input_name}")
            return

        if not output_path.exists():
            await message.answer(f"❌ Не удалось создать сжатый файл: {output_name}")
            return

        # Проверяем размер сжатого файла
        compressed_size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Сжатый файл: {compressed_size_mb:.1f} МБ")

        # Telegram имеет лимит 50 МБ для видео
        if compressed_size_mb > 50:
            await message.answer(
                f"❌ Сжатый файл всё ещё слишком большой ({compressed_size_mb:.1f} МБ). Попробуйте использовать файл меньшего размера.")
            return

        # Отправляем как видео
        with open(output_path, "rb") as f:
            await message.answer_video(
                BufferedInputFile(f.read(), filename=output_name),
                caption=caption or "Видеоинструкция"
            )

        logger.info(
            f"Видео {input_name} успешно отправлено (было: {file_size_mb:.1f} МБ, стало: {compressed_size_mb:.1f} МБ)")

    except FileNotFoundError:
        logger.error(f"Файл не найден: {input_path}")
        await message.answer(f"❌ Файл не найден: {input_name}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при отправке видео {input_name}: {e}")
        await message.answer(f"❌ Произошла ошибка при отправке видео: {str(e)}")
    finally:
        # Удаляем временный файл
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError as e:
            logger.warning(f"Не удалось удалить временный файл {output_name}: {e}")


# Функция проверки доступа
async def check_access(username: str) -> bool:
    if username in ALLOWED_USERS:
        return True
    logger.warning(f"Попытка доступа запрещена для пользователя: {username}")
    return False


# Декоратор для проверки доступа
def access_check(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        username = f"@{message.from_user.username}" if message.from_user.username else None
        if not username or not await check_access(username):
            await message.answer("⛔ Доступ запрещен. Вы не авторизованы для использования этого бота.")
            return
        return await func(message, *args, **kwargs)

    return wrapper

# Декоратор для проверки админских прав
def admin_check(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        username = f"@{message.from_user.username}" if message.from_user.username else None
        if not username or not await check_admin(username):
            await message.answer("⛔ Доступ запрещен. Только администраторы могут добавлять события.")
            return
        return await func(message, *args, **kwargs)
    return wrapper


# Улучшенные клавиатуры
def build_keyboard(buttons: list, row_width: int = 2):
    builder = ReplyKeyboardBuilder()
    for button in buttons:
        builder.add(KeyboardButton(text=button))
    builder.adjust(row_width)
    return builder.as_markup(resize_keyboard=True)


def clean_old_events(days=1):
    """Удаляет события, завершившиеся более days дней назад"""
    conn = None
    try:
        conn = sqlite3.connect('events.db')
        c = conn.cursor()

        # Удаляем события, которые завершились раньше чем X дней назад
        delete_time_utc = (datetime.datetime.now(UTC_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        # Логируем перед удалением
        c.execute("SELECT COUNT(*) FROM events WHERE event_date < ?", (delete_time_utc,))
        count_before = c.fetchone()[0]

        c.execute("DELETE FROM events WHERE event_date < ?", (delete_time_utc,))
        deleted_count = c.rowcount
        conn.commit()

        logger.info(f"Удалено {deleted_count}/{count_before} старых событий (старше {days} дней)")
    except Exception as e:
        logger.error(f"Ошибка при удалении старых событий: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def get_start_menu():
    return build_keyboard(["Начало"], 1)


def get_main_menu(username: str = None):
    # Основные кнопки для всех пользователей
    base_buttons = [
        "Инструкции", "Обучение инструкторов",
        "Справочник"
    ]

    # Если пользователь администратор - добавляем кнопку календаря вместо отдельных кнопок событий
    if username and username in ADMIN_USERS:
        base_buttons.append("Календарь")  # Заменяем три кнопки на одну

    return build_keyboard(base_buttons, 3)

def get_handbook_menu():
    return build_keyboard([
        "Контакты ПМ", "ИНН",
        "Бланки возврата", "Карточки организаций",
        "Вернуться к меню"
    ], 2)


# Добавим новую функцию для меню календаря
def get_calendar_menu():
    return build_keyboard([
        "Добавить событие", "Мои события",
        "Удалить событие", "Вернуться к меню"
    ], 2)

# Добавим функцию для кнопки отмены
def get_cancel_keyboard():
    return build_keyboard(["Отмена"], 1)



def get_instructions_menu():
    return build_keyboard([
        "Как именовать отчёты",
        "График и зп табель",
        "Инспекция ИСС",
        "Наличные",
        "Инвентаризация",  # Добавлена новая кнопка
        "Вернуться к меню"
    ], 2)

def get_inventory_menu():
    return build_keyboard([
        "Алгоритм", "Как проводить?",
        "Закрывашки", "Частые вопросы",
        "Как оформить заказ (видеоинструкции)",
        "Вернуться к инструкциям"
    ], 2)

def get_order_video_menu():
    return build_keyboard([
        "Леруа", "Комус",
        "Всеинструменты",
        "Назад к инвентаризации"
    ], 2)

def get_cash_menu():
    return build_keyboard([
        "Алгоритм", "Как тратим",
        "Результат", "Вернуться к инструкциям"  # Изменил название для соответствия фото
    ], 2)

def get_instructors_menu():
    return build_keyboard([
        "Чек-лист стажёра",
        "Когда выводить на полную ставку?",  # Новая кнопка
        "Документы для оформления",  # Новая кнопка
        "Вернуться к меню"
    ], 2)


def get_parks_menu():
    return build_keyboard(["Кошкино", "Уктус", "Дубрава", "Нижний", "Тюмень", "Назад"], 2)





def get_schedule_menu():
    return build_keyboard([
        "Составление графика",
        "Алгоритм",
        "Как должен выглядеть результат",
        "Вернуться к инструкциям"
    ], 2)


def get_inspection_menu():
    return build_keyboard([
        "Алгоритм",
        "Что делать со списанным снаряжением",
        "Как должен выглядеть результат",
        "Вернуться к инструкциям"
    ], 2)


# Функции для работы с календарем
def save_event(event_date, event_text, remind_before, user_id, chat_id, comment=""):
    try:
        # Парсим введенную дату как наивное время (предполагаем MSK)
        naive_dt = datetime.datetime.strptime(event_date, "%d.%m.%Y %H:%M")
        logger.info(f"Введенное время (наивное): {naive_dt}")

        # Добавляем MSK TZ
        msk_dt = naive_dt.replace(tzinfo=MSK_TZ)
        logger.info(f"Введенное время (MSK): {msk_dt}")

        # Преобразуем в UTC
        utc_dt = msk_dt.astimezone(UTC_TZ)
        event_date_sql = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Сохраненное время (UTC): {event_date_sql}")

        conn = sqlite3.connect('events.db')
        c = conn.cursor()
        c.execute("PRAGMA table_info(events)")
        columns = [col[1] for col in c.fetchall()]
        has_comment = 'comment' in columns

        if has_comment:
            c.execute(
                "INSERT INTO events (park, event_date, event_text, remind_before, user_id, chat_id, comment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Общее", event_date_sql, event_text, remind_before, user_id, chat_id, comment)
            )
        else:
            c.execute(
                "INSERT INTO events (park, event_date, event_text, remind_before, user_id, chat_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("Общее", event_date_sql, event_text, remind_before, user_id, chat_id)
            )
            logger.warning("Столбец 'comment' отсутствует, сохранено без комментария")

        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при сохранении события: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def get_user_events(user_id):
    """Получаем все будущие события пользователя"""
    conn = sqlite3.connect('events.db')
    c = conn.cursor()
    now_utc = datetime.datetime.now(UTC_TZ).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT * FROM events WHERE user_id=? AND event_date >= ? ORDER BY event_date", (user_id, now_utc))
    events = c.fetchall()

    # Логируем структуру события
    if events:
        logger.info(f"Структура события: {len(events[0])} полей")

    conn.close()
    return events


def get_events_to_remind():
    conn = sqlite3.connect('events.db')
    c = conn.cursor()

    # Получаем текущее время в UTC
    now_utc = datetime.datetime.now(UTC_TZ).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Текущее время UTC: {now_utc}")

    # Запрос в UTC
    query = """
        SELECT 
            id, park, event_date, event_text, remind_before, user_id, chat_id, reminded, comment
        FROM events 
        WHERE reminded = 0 
        AND datetime(event_date, '-' || remind_before || ' minutes') <= datetime('now')
        """

    try:
        c.execute(query)
        events = c.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQL при выборе событий: {e}")
        events = []

    logger.info(f"Найдено событий: {len(events)}")

    for event in events:
        event_id, park, event_date, event_text, remind_before, user_id, chat_id, reminded, comment = event
        logger.info(f"Событие ID {event_id}: Дата (UTC): {event_date}")

    conn.close()
    return events


def mark_event_reminded(event_id):
    conn = sqlite3.connect('events.db')
    c = conn.cursor()
    c.execute("UPDATE events SET reminded=1 WHERE id=?", (event_id,))
    conn.commit()
    conn.close()


# Фоновая задача для проверки напоминаний
async def check_reminders():
    logger.info("Запуск проверки напоминаний")
    while True:
        try:
            events = get_events_to_remind()
            logger.info(f"Событий для напоминания: {len(events)}")

            # Получаем chat_id всех авторизованных пользователей
            chat_ids = get_allowed_users_chat_ids()
            logger.info(f"Чат-IDs для рассылки: {chat_ids}")

            if not chat_ids:
                logger.warning("Нет пользователей для рассылки напоминаний")

            for event in events:
                # Распаковка 9 значений
                event_id, park, event_date_utc, event_text, remind_minutes, user_id, chat_id_val, reminded_flag, comment = event

                # Преобразуем минуты в часы
                hours = remind_minutes // 60

                # Конвертируем UTC в MSK для отображения
                utc_dt = datetime.datetime.strptime(event_date_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC_TZ)
                msk_dt = utc_dt.astimezone(MSK_TZ)
                # На следующий код:
                month_names = [
                    "января", "февраля", "марта", "апреля", "мая", "июня",
                    "июля", "августа", "сентября", "октября", "ноября", "декабря"
                ]
                day = msk_dt.day
                month = month_names[msk_dt.month - 1]
                time_str = msk_dt.strftime("%H:%M")
                event_time_str = f"{day} {month} {time_str}"

                # Формируем текст напоминания
                reminder_text = (
                    "🌳 Напоминалка\n\n"
                    f" Мероприятие: {event_text}\n"
                    f" Дедлайн: {event_time_str}\n"
                )

                if comment:
                    reminder_text += f"\n💬 Комментарий: {comment}\n\n"

                # Отправляем всем авторизованным пользователям
                for user_chat_id in chat_ids:
                    try:
                        await bot.send_message(chat_id=user_chat_id, text=reminder_text)
                        logger.info(f"Напоминание отправлено в чат {user_chat_id} для события {event_id}")
                    except Exception as e:
                        logger.error(f"Ошибка отправки в чат {user_chat_id}: {e}")

                # Помечаем событие как обработанное
                mark_event_reminded(event_id)

        except Exception as e:
            logger.error(f"Ошибка в задаче напоминаний: {e}", exc_info=True)
            await asyncio.sleep(10)

        await asyncio.sleep(30)


# Обработчики команд
@dp.message(Command("start"))
@access_check
async def cmd_start(message: types.Message, state: FSMContext, **kwargs):
    # Сохраняем/обновляем информацию о пользователе
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    chat_id = message.chat.id

    conn = sqlite3.connect('events.db')
    c = conn.cursor()

    # Создаем таблицу пользователей, если ее нет
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT NOT NULL UNIQUE,
                 chat_id INTEGER NOT NULL)''')

    # Добавляем/обновляем пользователя
    c.execute("INSERT OR REPLACE INTO users (username, chat_id) VALUES (?, ?)",
              (username, chat_id))

    conn.commit()
    conn.close()

    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(username))

# Обработчик для кнопки "Календарь"
@dp.message(lambda message: message.text == "Календарь")
@access_check
@admin_check
async def calendar_menu(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.in_calendar)
    await message.answer("📅 Меню календаря:", reply_markup=get_calendar_menu())


@dp.message(lambda message: message.text == "Начало")
@access_check
async def handle_start_button(message: types.Message, state: FSMContext, **kwargs):
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    await message.answer("👋 Добро пожаловать! Выберите действие:",
                         reply_markup=get_main_menu(username))

# Обработчики для кнопок в меню календаря
@dp.message(Form.in_calendar, lambda message: message.text == "Добавить событие")
@access_check
@admin_check
async def add_event_start(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.waiting_for_event_date)
    await message.answer("Введите дату и время события в формате ДД.ММ.ГГГГ ЧЧ:ММ (например, 31.12.2025 15:00):",
                         reply_markup=get_cancel_keyboard())

# Обработчики для кнопки "Отмена" - должны быть объявлены ДО обработчиков ввода данных
@dp.message(Form.waiting_for_event_date, lambda message: message.text == "Отмена")
@dp.message(Form.waiting_for_event_text, lambda message: message.text == "Отмена")
@dp.message(Form.waiting_for_remind_before, lambda message: message.text == "Отмена")
@dp.message(Form.waiting_for_comment, lambda message: message.text == "Отмена")
@dp.message(Form.waiting_for_event_to_delete, lambda message: message.text == "Отмена")
@access_check
@admin_check
async def cancel_operation(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.in_calendar)
    await message.answer("❌ Операция отменена.", reply_markup=get_calendar_menu())

@dp.message(Form.waiting_for_event_date)
@access_check
@admin_check
async def process_event_date(message: types.Message, state: FSMContext, **kwargs):
    try:
        # Проверка формата даты
        datetime.datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        await state.update_data(event_date=message.text)
        await state.set_state(Form.waiting_for_event_text)
        await message.answer("Введите описание события:", reply_markup=get_cancel_keyboard())
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте формат ДД.ММ.ГГГГ ЧЧ:ММ (например, 31.12.2025 15:00)")

@dp.message(Form.waiting_for_event_text)
@access_check
@admin_check
async def process_event_text(message: types.Message, state: FSMContext, **kwargs):
    await state.update_data(event_text=message.text)
    await state.set_state(Form.waiting_for_remind_before)
    await message.answer("За сколько часов до события напомнить? (введите целое число):", reply_markup=get_cancel_keyboard())

@dp.message(Form.waiting_for_remind_before)
@access_check
@admin_check
async def process_remind_before(message: types.Message, state: FSMContext, **kwargs):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError

        minutes = hours * 60
        await state.update_data(remind_before=minutes)

        # Переходим к вводу комментария
        await state.set_state(Form.waiting_for_comment)
        await message.answer("💬 Добавьте комментарий к событию (или напишите '-' чтобы пропустить):", reply_markup=get_cancel_keyboard())
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое положительное число часов.")

@dp.message(Form.waiting_for_comment)
@access_check
@admin_check
async def process_comment(message: types.Message, state: FSMContext, **kwargs):
    comment = message.text
    if comment.strip() == "-":
        comment = ""  # Пропуск комментария

    data = await state.get_data()
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)

    save_event(
        event_date=data['event_date'],
        event_text=data['event_text'],
        remind_before=data['remind_before'],
        user_id=username,
        chat_id=message.chat.id,
        comment=comment
    )

    # Форматируем дату для подтверждения (в MSK)
    naive_dt = datetime.datetime.strptime(data['event_date'], "%d.%m.%Y %H:%M")
    msk_dt = naive_dt.replace(tzinfo=MSK_TZ)
    month_names = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    day = msk_dt.day
    month = month_names[msk_dt.month - 1]
    time_str = msk_dt.strftime("%H:%M")
    formatted_date = f"{day} {month} {msk_dt.year} в {time_str}"
    response = (
        f"✅ Событие успешно добавлено!\n\n"
        f" Дедлайн: {formatted_date}\n"
        f" Мероприятие: {data['event_text']}\n"
        f" Напоминание за {data['remind_before'] // 60} часов до события"
    )

    if comment:
        response += f"\n\n💬 Комментарий: {comment}"

    await message.answer(response)
    await state.set_state(Form.in_calendar)
    await message.answer("📅 Меню календаря:", reply_markup=get_calendar_menu())

@dp.message(Form.in_calendar, lambda message: message.text == "Мои события")
@access_check
@admin_check
async def show_user_events(message: types.Message, **kwargs):
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    events = get_user_events(username)

    if not events:
        await message.answer("📅 У вас нет предстоящих событий.", reply_markup=get_calendar_menu())
        return

    response = "📅 Ваши предстоящие события:\n\n"
    for event in events:
        # Правильная индексация полей
        event_id = event[0]
        event_date_utc = event[2]  # UTC время
        event_text = event[3]
        remind_minutes = event[4]
        comment = event[8] if len(event) > 8 else ""  # Комментарий (с проверкой)

        # Конвертируем UTC в MSK
        utc_dt = datetime.datetime.strptime(event_date_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC_TZ)
        msk_dt = utc_dt.astimezone(MSK_TZ)
        event_time = msk_dt.strftime("%d.%m.%Y %H:%M")

        # Преобразуем минуты в часы
        hours = remind_minutes // 60

        response += f"🆔 ID: {event_id}\n"
        response += f" Время: {event_time}\n"
        response += f" Мероприятие: {event_text}\n"
        if comment:
            response += f"💬 Комментарий: {comment}\n"
        response += f"⏱ Напоминание за {hours} часов до события\n"
        response += "────────────────────\n"

    await message.answer(response, reply_markup=get_calendar_menu())


@dp.message(Form.in_calendar, lambda message: message.text == "Удалить событие")
@access_check
@admin_check
async def delete_event_start(message: types.Message, state: FSMContext, **kwargs):
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    events = get_user_events(username)

    if not events:
        await message.answer("📅 У вас нет предстоящих событий для удаления.", reply_markup=get_calendar_menu())
        return

    # Формируем список событий с ID
    response = "📅 Ваши предстоящие события:\n\n"
    for event in events:
        event_id = event[0]
        event_date_utc = event[2]
        event_text = event[3]

        # Конвертируем в MSK
        utc_dt = datetime.datetime.strptime(event_date_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC_TZ)
        msk_dt = utc_dt.astimezone(MSK_TZ)
        event_time = msk_dt.strftime("%d.%m.%Y %H:%M")

        response += f"🆔 ID: {event_id}\n"
        response += f"⏰ Время: {event_time}\n"
        response += f"📝 Событие: {event_text}\n"
        response += "────────────────────\n"

    response += "\nВведите ID события, которое хотите удалить (или нажмите 'Отмена'):"
    await message.answer(response, reply_markup=get_cancel_keyboard())
    await state.set_state(Form.waiting_for_event_to_delete)

# Обработчик для кнопки "Вернуться к меню" в календаре
@dp.message(Form.in_calendar, lambda message: message.text == "Вернуться к меню")
@access_check
@admin_check
async def calendar_back_to_main(message: types.Message, state: FSMContext, **kwargs):
    await state.clear()
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(username))



@dp.message(Form.waiting_for_event_to_delete)
@access_check
async def process_event_delete(message: types.Message, state: FSMContext, **kwargs):
    conn = None
    try:
        event_id = int(message.text)
        username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)

        # Проверяем существование события и принадлежность пользователю
        conn = sqlite3.connect('events.db')
        c = conn.cursor()
        c.execute("SELECT id FROM events WHERE id=? AND user_id=?", (event_id, username))
        event_exists = c.fetchone()

        if event_exists:
            c.execute("DELETE FROM events WHERE id=?", (event_id,))
            conn.commit()
            await message.answer(f"✅ Событие с ID {event_id} успешно удалено!")
        else:
            await message.answer("❌ Событие с таким ID не найдено или вы не являетесь его создателем.")
    except ValueError:
        await message.answer("❌ Пожалуйста, введите числовой ID события.")
    except Exception as e:
        logger.error(f"Ошибка при удалении события: {e}")
        await message.answer("❌ Произошла ошибка при удалении события.")
    finally:
        if conn:
            conn.close()
        await state.set_state(Form.in_calendar)
        await message.answer("📅 Меню календаря:", reply_markup=get_calendar_menu())

@dp.message(lambda message: message.text == "Инструкции")
@access_check
async def select_instructions(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.in_instructions)
    await message.answer("📋 Выбери инструкцию:", reply_markup=get_instructions_menu())

@dp.message(lambda message: message.text == "Обучение инструкторов")
@access_check
async def select_instructors(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.in_training)
    await message.answer("👨‍🏫 Выбери раздел обучения:", reply_markup=get_instructors_menu())


@dp.message(Form.in_instructions)
@access_check
async def process_instructions(message: types.Message, state: FSMContext, **kwargs):
    if message.text == "Вернуться к меню":
        await state.clear()
        await cmd_start(message, state)
        return


    if message.text == "Наличные":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("Наличные:", reply_markup=get_cash_menu())
    elif message.text == "График и зп табель":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("📅 График и зп табель:", reply_markup=get_schedule_menu())
    elif message.text == "Инспекция ИСС":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("🔍 Инспекция ИСС:", reply_markup=get_inspection_menu())
    elif message.text == "Как именовать отчёты":
        await message.answer("📝 Правила именования документов:\n\n"
                "Для всех плановых мероприятий создаем новые листы (бэкапим)\n\n"
                "• ЗП табель: ЗП Парк период\n"
                "Пример: ЗП Кошкино 16.07.-31.07.\n\n"
                "• Счета: Хозрасходы Парк Магазин Дата формирования счета\n"
                "Пример: Хозрасходы Кошкино Комус 12.05.\n\n"
                "• Отчет по наличным: Парк Хозрасходы Месяц\n"
                "Пример: Кошкино Хозрасходы июнь\n\n"
                "• Инспекция ИСС: Инспекция ИСС Дата\n"
                "Пример: Инспекция ИСС 15.08.2023", reply_markup=get_instructions_menu())
    elif message.text == "Инвентаризация":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("📦 Инвентаризация:", reply_markup=get_inventory_menu())
    else:
        await message.answer("📋 Используйте кнопки для навигации", reply_markup=get_instructions_menu())


@dp.message(Form.in_training)
@access_check
async def process_training(message: types.Message, state: FSMContext, **kwargs):
    if message.text == "Вернуться к меню":
        await state.clear()
        await cmd_start(message, state)
        return

    if message.text == "Чек-лист стажёра":
        await message.answer(f"https://docs.google.com/spreadsheets/d/1znrHWMowytgYcWlTZwyzJFmlh1hEL2sI-D6tnPTSYvM/edit?gid=0#gid=0")
        try:
            # Отправляем PDF файл
            with open("чек-лист стажёры.pdf", "rb") as pdf_file:
                await message.answer_document(
                    BufferedInputFile(
                        pdf_file.read(),
                        filename="чек-лист стажёры.pdf"
                    ),
                    caption="📄 Чек-лист стажёра в формате PDF"
                )
        except FileNotFoundError:
            await message.answer("❌ Файл чек-листа не найден")
        except Exception as e:
            logger.error(f"Ошибка отправки PDF: {e}")
            await message.answer("❌ Произошла ошибка при отправке файла")
        await message.answer("👨‍🏫 Выбери раздел обучения:", reply_markup=get_instructors_menu())

    elif message.text == "Когда выводить на полную ставку?":
        response = (
            "📌 Когда инструктора можно выводить на полную ставку?\n\n"
            "Когда стажёр сдал все основные зачеты:\n"
            "✅ Знание допусков посетителя (внешний вид и здоровье)\n"
            "✅ Правильное заполнение техники безопасности\n"
            "✅ Проведение инструктажа (вместе с картой)\n"
            "✅ Спасательные работы на время:\n"
            "   - Спуск с этапа\n"
            "   - Спуск с платформы\n"
            "   - Работа в тандеме\n"
            "   - Самоспуск\n"
            "✅ Надевание снаряжения (взрослое/детское, шлемы)\n"
            "✅ Уверенная работа с кассовым ПО:\n"
            "   - Продажа билетов\n"
            "   - Продажа сопутствующих товаров\n\n"
            "⏱ Оптимальное время обучения: 3-5 смен\n"
            "❌ Не рекомендуется более 7 стажерских смен"
        )
        await message.answer(response)

    elif message.text == "Документы для оформления":
        response = (
            "📋 Документы для оформления инструктора:\n\n"
            "• Паспорт (главная страница + прописка)\n"
            "• СНИЛС (страховое свидетельство)\n"
            "• ИНН (индивидуальный номер налогоплательщика)\n"
            "• Электронная выписка из трудовой книжки (при наличии)\n"
            "• Реквизиты карты для ЗП (полные реквизиты из ЛК банка, не только номер карты)\n\n"
            "📌 Порядок оформления:\n"
            "1. Собрать все документы\n"
            "2. Создать папку с названием в формате: 'Фамилия_Имя_Отчество'\n"
            "3. Заархивировать папку\n"
            "4. Отправить архив операционному директору для оформления"
        )
        await message.answer(response)


@dp.message(lambda message: message.text == "Справочник")
@access_check
async def select_handbook(message: types.Message, state: FSMContext, **kwargs):
    await state.set_state(Form.in_section)
    await state.update_data(current_section="Справочник")
    await message.answer("📚 Выберите раздел:", reply_markup=get_handbook_menu())



@dp.message(Form.in_section)
@access_check
async def process_section(message: types.Message, state: FSMContext, **kwargs):
    data = await state.get_data()
    current_section = data.get("current_section")

    if message.text == "Вернуться к меню":
        await state.clear()
        username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
        await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(username))
        return

    # Новый раздел: Справочник
    if current_section == "Справочник":
        if message.text == "Контакты ПМ":
            text = (
                "Парк-менеджеры:\n\n"
                "Кошкино\n"
                "СДЕК: Областная ул., 1\n"
                "Астратов Роман Юрьевич\n"
                "+79218621492\n"
                "[@astratov_roman](https://t.me/astratov_roman)\n\n"
                "Тюмень\n"
                "СДЕК: Андрея Кореневского 11\n"
                "Охрямкина Анастасия Вадимовна \n"
                "89504873768\n"
                "[@vaditmn](https://t.me/vaditmn)\n\n"
                "Нижний\n"
                "СДЕК: Нижегородская обл., г.Бор, ул. Маяковского, 1А\n"
                "Арсиев Эрнест Александрович\n"
                "+79867277470\n"
                "[@milkenxxx](https://t.me/milkenxxx)\n\n"
                "Уктус\n"
                "СДЕК: Щербакова 35\n"
                "Михайлова Эвелина Сергеевна\n"
                "+79920208237\n"
                "[@loreley1264](https://t.me/loreley1264)\n\n"
                "Дубрава\n"
                "СДЕК: Щербакова 35\n"
                "Бурлакова Ольга Григорьевна \n"
                "+79193727914\n"
                "[@olikburlakova](https://t.me/olikburlakova)"
            )
            await message.answer(text, parse_mode="Markdown", reply_markup=get_handbook_menu())
            return

        if message.text == "ИНН":
            text = (
                "ИНН:\n\n"
                "Зеленый треугольник: 7839504361\n"
                "ПК7 Екатеринбург: 7839102736\n"
                "ПК7 Нижний: 5246056919\n"
                "ПК7 Тюмень: 7838115620\n"
                "Дубрава-парк: 6670343533"
            )
            await message.answer(text, reply_markup=get_handbook_menu())
            return

        if message.text == "Бланки возврата":
            # Отправка всех PDF одним сообщением медиагруппой, либо последовательно
            files = [
                "Бланк для возврата Кошкино.pdf",
                "Бланк для возврата Екатеринбург.pdf",
                "Бланк для возврата НН.pdf",
                "Бланк для возврата Тюмень.pdf",
                "Бланк для возврата Дубрава.pdf",
            ]
            # Вариант 1: несколько сообщений по одному документу:
            for fpath in files:
                try:
                    with open(fpath, "rb") as f:
                        await message.answer_document(
                            BufferedInputFile(f.read(), filename=fpath)
                        )
                        await asyncio.sleep(0.2)
                except FileNotFoundError:
                    await message.answer(f"❌ Файл не найден: {fpath}")
            await message.answer("Бланки возврата для каждого парка.", reply_markup=get_handbook_menu())
            return

        if message.text == "Карточки организаций":
            files = [
                "Карточка ООО Зеленый Треуголник.pdf",
                "Карточка ООО ПК7 Екатеринбург.pdf",
                "Карточка ООО ПК7 Нижний.pdf",
                "Карточка ООО ПК7 Тюмень.pdf",
                "Карточка ООО Дубрава-Парк.pdf",
            ]

            # Отправляем каждый файл отдельным сообщением
            for fpath in files:
                try:
                    with open(fpath, "rb") as f:
                        await message.answer_document(
                            BufferedInputFile(f.read(), filename=fpath)
                        )
                    await asyncio.sleep(0.2)
                except FileNotFoundError:
                    await message.answer(f"❌ Файл не найден: {fpath}")

            await message.answer("Карточки организаций для каждого парка.", reply_markup=get_handbook_menu())
            return

        await message.answer("📚 Используйте кнопки для навигации", reply_markup=get_handbook_menu())
        return

    if message.text == "Вернуться к инструкциям":
        await state.set_state(Form.in_instructions)
        await message.answer("📋 Выбери инструкцию:", reply_markup=get_instructions_menu())
        return

    if current_section == "Инвентаризация":
        # Обработка видеоинструкций - ВЫНЕСЕНО ИЗ TRY БЛОКА
        if data.get("subsection") == "order_videos":
            if message.text == "Назад к инвентаризации":
                await state.update_data(subsection=None)
                await message.answer("📦 Инвентаризация:", reply_markup=get_inventory_menu())
                return

            # Словарь соответствий кнопок и файлов
            video_files_map = {
                "Леруа": "Леруа Как оформить заказ.mp4",
                "Комус": "Комус Как оформить заказ.mp4",
                "Всеинструменты": "Всеинстурменты Как оформить заказ.mp4"
                # Обратите внимание на опечатку в названии файла
            }

            button_text = message.text.strip()

            if button_text not in video_files_map:
                await message.answer(f"❌ Неизвестный поставщик: {button_text}")
                await message.answer("Выберите поставщика:", reply_markup=get_order_video_menu())
                return

            video_filename = video_files_map[button_text]
            video_path = VIDEO_DIR / video_filename

            if not video_path.exists():
                logger.error(f"Видеофайл не найден: {video_path}")
                await message.answer(f"❌ Видеофайл не найден: {video_filename}")
                await message.answer("Выберите поставщика:", reply_markup=get_order_video_menu())
                return

            try:
                await send_compressed_video(
                    message,
                    input_name=video_filename,
                    caption=f"Видеоинструкция: Как оформить заказ в {button_text}"
                )
                await message.answer("Выберите поставщика:", reply_markup=get_order_video_menu())
            except Exception as e:
                logger.error(f"Ошибка при отправке видео {video_filename}: {e}")
                await message.answer(f"❌ Произошла ошибка при отправке видео для {button_text}")
                await message.answer("Выберите поставщика:", reply_markup=get_order_video_menu())

            return

        # Остальные кнопки инвентаризации - В TRY БЛОКЕ
        try:
            if message.text == "Алгоритм":
                with open("инвент алгоритм.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="inventory_algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inventory_menu())

            elif message.text == "Как проводить?":
                # Отправляем 3 фото последовательно
                files = [
                    "инвент как проводить 1.jpg",
                    "инвент как проводить 2.jpg",
                    "инвент как проводить 3.jpg"
                ]
                for file in files:
                    with open(file, "rb") as photo:
                        await message.answer_photo(BufferedInputFile(photo.read(), filename=file))
                    await asyncio.sleep(0.5)  # Задержка между сообщениями
                await message.answer("Выберите следующий раздел:", reply_markup=get_inventory_menu())

            elif message.text == "Закрывашки":
                with open("инвент закрывашки.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="inventory_closing.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inventory_menu())

            elif message.text == "Частые вопросы":
                faq_text = (
                    "❓ Частые вопросы по инвентаризации:\n\n"
                    "🔹 В таблице инвентаризации нет товара, который нужен\n"
                    "• Если стоимость товара > 5000р. - согласуй с опер.дир-ом\n"
                    "• Если товар дешевле, но парк не заказывает регулярно - добавляй в заказ и согласуй\n\n"
                    "🔹 У поставщика нет нужного товара, можно купить за наличку?\n"
                    "• Да, если товар недорогой (мусорные пакеты, туалетная бумага и т.д.)\n"
                    "• Если > 5000р. - оформляй по безналу или согласуй с опер.диром\n\n"
                    "🔹 МНЕ СРОЧНО\n"
                    "• Если счёт требует срочной оплаты не в день инвентаризации:\n"
                    " Оформляй и отправляй в беседу со словом 'СРОЧНО'\n\n"
                    "🔹 OZON\n"
                    "• Заказы с Ozon нежелательны (проблемы с документами у бухгалтерии)\n"
                    "• Допустимы только редкие заказы, в основном заказываем у основных поставщиков\n\n"
                    "🔹 Нам доставили гайковерт, но он не подходит. Что делать?\n"
                    "• Если заказали неподходящий товар по безналу:\n"
                    " 1. Сообщи офис-менеджеру\n"
                    " 2. Оформи доверенность на возврат\n"
                    " 3. Верни товар в магазин с доверенностью"
                )
                await message.answer(faq_text)
                await message.answer("Выберите следующий раздел:", reply_markup=get_inventory_menu())

            elif message.text == "Как оформить заказ (видеоинструкции)":
                await state.update_data(subsection="order_videos")
                await message.answer("Выберите поставщика:", reply_markup=get_order_video_menu())

        except FileNotFoundError as e:
            await message.answer(f"❌ Файл не найден: {e}")
            logger.error(f"File not found: {e}")



    if current_section == "Наличные":
        try:
            if message.text == "Алгоритм":
                with open("алгоритм Наличка.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="cash_algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_cash_menu())

            elif message.text == "Как тратим":
                with open("как тратим Наличка.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="cash_spending.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_cash_menu())

            elif message.text == "Результат":
                with open("результат Наличка.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="cash_result.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_cash_menu())

            elif message.text == "Вернуться к инструкциям":
                await state.set_state(Form.waiting_for_instructor)
                await message.answer("📋 Выбери инструкцию:", reply_markup=get_instructions_menu())

            elif message.text == "Вернуться к меню":
                await state.clear()
                await cmd_start(message, state)

        except FileNotFoundError as e:
            await message.answer(f"❌ Файл не найден: {e}")
            logger.error(f"File not found: {e}")

    if current_section == "График и зп табель":
        try:
            if message.text == "Составление графика":
                # Отправляем каждое фото отдельным сообщением
                files = [
                    "1 инстр графикЗП.jpg",
                    "2 инстр графикЗП.jpg",
                    "3 инстр графикЗП.jpg"
                ]

                for file in files:
                    with open(file, "rb") as photo:
                        await message.answer_photo(BufferedInputFile(photo.read(), filename=file))
                    await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

                await message.answer("Выберите следующий раздел:", reply_markup=get_schedule_menu())

            elif message.text == "Как должен выглядеть результат":
                # Отправляем каждое фото отдельным сообщением
                files = [
                    "результат ЗП табель.jpg",
                    "результат график.jpg"
                ]

                for file in files:
                    with open(file, "rb") as photo:
                        await message.answer_photo(BufferedInputFile(photo.read(), filename=file))
                    await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

                await message.answer("Выберите следующий раздел:", reply_markup=get_schedule_menu())

            elif message.text == "Алгоритм":
                with open("алгоритм графикЗП.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_schedule_menu())



            elif message.text == "Вернуться к меню":
                await state.clear()
                await cmd_start(message, state)

        except FileNotFoundError as e:
            await message.answer(f"Ошибка: файл не найден ({e})")
            logger.error(f"File not found: {e}")

    elif current_section == "Инспекция ИСС":
        try:
            if message.text == "Алгоритм":
                with open("алгоритм ИСС.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="inspection_algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inspection_menu())

            elif message.text == "Что делать со списанным снаряжением":

                await message.answer("Для таких случаев, необходимо организовать отдельное место хранения. \n\n"
                                     
                                     "В конце сезона сообщить опер. директору.")
                await message.answer("Выберите следующий раздел:", reply_markup=get_inspection_menu())

            elif message.text == "Как должен выглядеть результат":
                with open("результат ИСС.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="inspection_result.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inspection_menu())

            elif message.text == "Вернуться к меню":
                await state.clear()
                await cmd_start(message, state)

        except FileNotFoundError as e:
            await message.answer(f"Ошибка: файл не найден ({e})")
            logger.error(f"File not found: {e}")

    elif "Вернуться к меню" in message.text:
        await state.clear()
        await cmd_start(message, state)



@dp.message()
@access_check
async def handle_other(message: types.Message, **kwargs):
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    await message.answer("ℹ Используйте кнопки меню для навигации", reply_markup=get_main_menu(username))



# Новый способ запуска бота
async def main():
    # Принудительно закрываем все предыдущие соединения
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(1)  # Даем время на закрытие соединений

    # Создаем задачи для фоновых процессов
    reminder_task = asyncio.create_task(check_reminders())
    clean_task = asyncio.create_task(clean_old_events_task())

    try:
        # Запускаем бота
        logger.info("Бот успешно запущен")
        await asyncio.sleep(5)  # Задержка 5 секунд перед запуском polling
        await dp.start_polling(bot, skip_updates=True, allowed_updates=[])
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки бота")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Отменяем только наши фоновые задачи, а не все
        reminder_task.cancel()
        clean_task.cancel()

        # Ждем завершения только наших задач
        try:
            await asyncio.wait_for(asyncio.gather(reminder_task, clean_task, return_exceptions=True), timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("Таймаут при ожидании завершения задач")

        # Закрываем сессию бота
        await bot.session.close()
        logger.info("Бот полностью остановлен")


if __name__ == '__main__':
    # Простой запуск с обработкой KeyboardInterrupt
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Ошибка: {e}")