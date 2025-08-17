from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto
import logging
from aiogram import Router
from aiogram.filters import BaseFilter

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7617868509:AAFf1Bfj6M872KnDMrrMHm6q5PzyYNjpsgs"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Список разрешенных пользователей
ALLOWED_USERS = {
    "@vaditmn",
    "@olikburlakova",
    "@astratov_roman",
    "@loreley1264",
    "@DashaRyzhova",
    "@veron144ka"
}

# Фильтр для проверки пользователей
class UserAccessFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return message.from_user.username in ALLOWED_USERS

class Form(StatesGroup):
    waiting_for_instructor = State()
    waiting_for_park = State()
    waiting_for_print = State()
    waiting_for_document = State()
    waiting_for_month = State()
    in_section = State()

# Улучшенные клавиатуры
def build_keyboard(buttons: list, row_width: int = 2):
    builder = ReplyKeyboardBuilder()
    for button in buttons:
        builder.add(KeyboardButton(text=button))
    builder.adjust(row_width)
    return builder.as_markup(resize_keyboard=True)

def get_main_menu():
    return build_keyboard([
        "Инструкции", "Обучение инструкторов",
        "Как проходит месяц", "Заказать полиграфию",
        "Документы"
    ], 2)

def get_instructions_menu():
    return build_keyboard([
        "Как именовать документы", "График и зп табель",
        "Инспекция ИСС", "Обход трасс",
        "Инвентаризация", "Отчет по наличным",
        "Вернуться к меню"
    ], 2)

def get_instructors_menu():
    return build_keyboard([
        "Чек-лист стажёра", "Вернуться к меню"
    ], 2)

def get_parks_menu():
    return build_keyboard(["Кошкино", "Уктус", "Дубрава", "Нижний", "Тюмень", "Назад"], 2)

def get_print_menu():
    return build_keyboard([
        "Типография для квестов", "Карта парка",
        "Таблички на деревья", "Кассовый домик",
        "Остальная полиграфия", "Вернуться к меню"
    ], 2)

def get_document_menu():
    return build_keyboard([
        "Бланк для возврата", "Уголок потребителя",
        "Справочник", "Вернуться к меню"
    ], 2)

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

# Обработчики с улучшенной логикой
@dp.message(Command("start"), UserAccessFilter())
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Добро пожаловать! Выбери действие:", reply_markup=get_main_menu())

@dp.message(lambda message: message.text == "Инструкции", UserAccessFilter())
async def select_instructions(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_instructor)
    await message.answer("📋 Выбери инструкцию:", reply_markup=get_instructions_menu())

@dp.message(lambda message: message.text == "Обучение инструкторов", UserAccessFilter())
async def select_instructors(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_instructor)
    await message.answer("👨‍🏫 Выбери раздел обучения:", reply_markup=get_instructors_menu())

@dp.message(lambda message: message.text == "Как проходит месяц", UserAccessFilter())
async def select_month_park(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_park)
    await state.update_data(section="Как проходит месяц")
    await message.answer("📅 Выбери парк:", reply_markup=get_parks_menu())

@dp.message(lambda message: message.text == "Заказать полиграфию", UserAccessFilter())
async def select_print_park(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_park)
    await state.update_data(section="Заказать полиграфию")
    await message.answer("🖨 Выбери парк:", reply_markup=get_parks_menu())

@dp.message(lambda message: message.text == "Документы", UserAccessFilter())
async def select_document_park(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_park)
    await state.update_data(section="Документы")
    await message.answer("📂 Выбери парк:", reply_markup=get_parks_menu())

@dp.message(Form.waiting_for_instructor, UserAccessFilter())
async def process_instructions(message: types.Message, state: FSMContext):
    if message.text == "Вернуться к меню":
        await state.clear()
        await cmd_start(message, state)
        return

    if message.text == "График и зп табель":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("📅 График и зп табель:", reply_markup=get_schedule_menu())
        return

    if message.text == "Инспекция ИСС":
        await state.set_state(Form.in_section)
        await state.update_data(current_section=message.text)
        await message.answer("🔍 Инспекция ИСС:", reply_markup=get_inspection_menu())
        return

    await state.set_state(Form.in_section)
    await state.update_data(current_section=message.text)
    if message.text == "Чек-лист стажёра":
        await message.answer(f"👨‍🏫 Чек-лист стажёра - здесь будет текст раздела", reply_markup=get_main_menu())
    else:
        await message.answer(f"📋 {message.text} - здесь будет текст раздела", reply_markup=get_instructions_menu())

@dp.message(Form.waiting_for_park, UserAccessFilter())
async def process_park(message: types.Message, state: FSMContext):
    if message.text == "Назад":
        await state.clear()
        await cmd_start(message, state)
        return

    data = await state.get_data()
    park = message.text
    section = data.get("section")

    await state.set_state(Form.in_section)
    await state.update_data(current_park=park)

    if section == "Как проходит месяц":
        await message.answer(f"📅 Календарь для парка {park} ", reply_markup=get_main_menu())
    elif section == "Заказать полиграфию":
        await state.set_state(Form.waiting_for_print)
        await message.answer(f"🖨 Выбери раздел полиграфии для парка {park}:", reply_markup=get_print_menu())
    elif section == "Документы":
        await state.set_state(Form.waiting_for_document)
        await message.answer(f"📂 Выбери раздел документов для парка {park}:", reply_markup=get_document_menu())

@dp.message(Form.waiting_for_print, UserAccessFilter())
async def process_print(message: types.Message, state: FSMContext):
    if message.text == "Вернуться к меню":
        await state.clear()
        await cmd_start(message, state)
        return
    await state.set_state(Form.in_section)
    await state.update_data(current_section=message.text)
    data = await state.get_data()
    park = data.get("current_park")
    await message.answer(f"🖨 {message.text} для парка {park} - здесь будет текст раздела", reply_markup=get_print_menu())

@dp.message(Form.waiting_for_document, UserAccessFilter())
async def process_document(message: types.Message, state: FSMContext):
    if message.text == "Вернуться к меню":
        await state.clear()
        await cmd_start(message, state)
        return
    await state.set_state(Form.in_section)
    await state.update_data(current_section=message.text)
    data = await state.get_data()
    park = data.get("current_park")
    await message.answer(f"📂 {message.text} для парка {park} - здесь будет текст раздела", reply_markup=get_document_menu())

@dp.message(Form.in_section, UserAccessFilter())
async def process_section(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_section = data.get("current_section")

    if message.text == "Вернуться к инструкциям":
        await state.set_state(Form.waiting_for_instructor)
        await message.answer("📋 Выбери инструкцию:", reply_markup=get_instructions_menu())
        return

    if current_section == "График и зп табель":
        try:
            if message.text == "Составление графика":
                with open("Составление графика.jpg", "rb") as photo1, \
                        open("Составление графика2.jpg", "rb") as photo2, \
                        open("Составление графика3.jpg", "rb") as photo3:

                    media = [
                        InputMediaPhoto(media=BufferedInputFile(photo1.read(), filename="graph1.jpg")),
                        InputMediaPhoto(media=BufferedInputFile(photo2.read(), filename="graph2.jpg")),
                        InputMediaPhoto(media=BufferedInputFile(photo3.read(), filename="graph3.jpg"))
                    ]
                    await message.answer_media_group(media=media)

                await message.answer("Выберите следующий раздел:", reply_markup=get_schedule_menu())

            elif message.text == "Алгоритм":
                with open("алгоритм графикЗП.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_schedule_menu())

            elif message.text == "Как должен выглядеть результат":
                with open("результат ЗП табель.jpg", "rb") as photo1, \
                        open("результат график.jpg", "rb") as photo2:

                    media = [
                        InputMediaPhoto(media=BufferedInputFile(photo1.read(), filename="result1.jpg")),
                        InputMediaPhoto(media=BufferedInputFile(photo2.read(), filename="result2.jpg"))
                    ]
                    await message.answer_media_group(media=media)

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
                with open("алгоритм инспекция.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="inspection_algorithm.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inspection_menu())

            elif message.text == "Что делать со списанным снаряжением":
                with open("списанное снаряжение.jpg", "rb") as photo:
                    await message.answer_photo(BufferedInputFile(photo.read(), filename="equipment.jpg"))
                await message.answer("Выберите следующий раздел:", reply_markup=get_inspection_menu())

            elif message.text == "Как должен выглядеть результат":
                with open("результат инспекции.jpg", "rb") as photo:
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
async def handle_other(message: types.Message):
    if message.from_user.username not in ALLOWED_USERS:
        await message.answer("❌ Доступ запрещен. Обратитесь к администратору.")
    else:
        await message.answer("ℹ Используйте кнопки меню для навигации", reply_markup=get_main_menu())

if __name__ == '__main__':
    logger.info("Бот запущен")
    try:
        dp.run_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка: {e}")