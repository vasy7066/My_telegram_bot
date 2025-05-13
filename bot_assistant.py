from pathlib import Path
import asyncio
import logging
import sqlite3
import aiohttp
import feedparser
from datetime import datetime, timedelta
from calendar import monthrange

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = "7558057961:AAHPEJr4dSEzbAC_G-VA880SyTBgt9qFgcQ"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# База данных
conn = sqlite3.connect("tasks.db")
cursor = conn.cursor()

# Создаем таблицы
cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    description TEXT,
    deadline TEXT,
    repeat TEXT DEFAULT 'никогда'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER PRIMARY KEY,
    completed INTEGER DEFAULT 0,
    uncompleted INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS finances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    category TEXT,
    description TEXT,
    date TEXT DEFAULT (strftime('%Y-%m-%d', 'now')))
""")
conn.commit()

# Если поля отсутствуют (для старой базы)
try:
    cursor.execute("ALTER TABLE tasks ADD COLUMN reminded INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass


# FSM
class TaskStates(StatesGroup):
    waiting_description = State()
    waiting_deadline = State()
    waiting_repeat = State()
    waiting_edit_id = State()
    waiting_edit_field = State()
    waiting_edit_value = State()
    waiting_weather_city = State()
    waiting_task_completion = State()
    waiting_finance_amount = State()
    waiting_finance_category = State()
    waiting_finance_description = State()


# Основная клавиатура
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить задачу"), KeyboardButton(text="📝 Список задач")],
            [KeyboardButton(text="✏️ Редактировать задачу"), KeyboardButton(text="❌ Удалить задачу")],
            [KeyboardButton(text="♻️ Еженедельные задачи"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="💱 Курс валют"), KeyboardButton(text="🌦️ Погода")],
            [KeyboardButton(text="📰 Новости"), KeyboardButton(text="💰 Финансы")]
        ],
        resize_keyboard=True
    )


# Клавиатура для финансов
def get_finance_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить расход"), KeyboardButton(text="📊 Статистика расходов")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )


# Клавиатура для категорий расходов
categories_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍔 Еда"), KeyboardButton(text="🏠 Жилье")],
        [KeyboardButton(text="🚗 Транспорт"), KeyboardButton(text="🛍️ Покупки")],
        [KeyboardButton(text="🎉 Развлечения"), KeyboardButton(text="💊 Здоровье")],
        [KeyboardButton(text="📚 Образование"), KeyboardButton(text="📱 Связь")],
        [KeyboardButton(text="🔧 Другое")]
    ],
    resize_keyboard=True
)

# Клавиатура для выбора повторения
repeat_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Никогда", callback_data="repeat_никогда")],
        [InlineKeyboardButton(text="Еженедельно", callback_data="repeat_еженедельно")]
    ]
)

# Клавиатура для выбора поля редактирования
edit_field_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Описание", callback_data="edit_description")],
        [InlineKeyboardButton(text="Дедлайн", callback_data="edit_deadline")],
        [InlineKeyboardButton(text="Повтор", callback_data="edit_repeat")]
    ]
)

# Клавиатура для подтверждения выполнения задачи
completion_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="complete_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="complete_no")]
    ]
)

# Клавиатура для выбора города
weather_cities_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Красноярск", callback_data="weather_Красноярск")],
        [InlineKeyboardButton(text="Другой город", callback_data="weather_other")]
    ]
)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    cursor.execute("INSERT OR IGNORE INTO stats (user_id, completed, uncompleted) VALUES (?, 0, 0)",
                   (message.from_user.id,))
    conn.commit()
    await message.answer("Привет! Я помощник. Выбери действие:", reply_markup=get_main_kb())


@dp.message(F.text == "💰 Финансы")
async def finances_menu(message: types.Message):
    await message.answer("Управление финансами:", reply_markup=get_finance_kb())


@dp.message(F.text == "➕ Добавить расход")
async def add_expense_start(message: types.Message, state: FSMContext):
    await state.set_state(TaskStates.waiting_finance_amount)
    await message.answer("Введите сумму расхода:", reply_markup=types.ReplyKeyboardRemove())


@dp.message(TaskStates.waiting_finance_amount)
async def process_expense_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        await state.update_data(amount=amount)
        await state.set_state(TaskStates.waiting_finance_category)
        await message.answer("Выберите категорию:", reply_markup=categories_kb)
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму (например: 1500 или 99.99)")


@dp.message(TaskStates.waiting_finance_category)
async def process_expense_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await state.set_state(TaskStates.waiting_finance_description)
    await message.answer("Введите описание расхода (необязательно):", reply_markup=types.ReplyKeyboardRemove())


@dp.message(TaskStates.waiting_finance_description)
async def process_expense_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    description = message.text if message.text else "Без описания"

    cursor.execute(
        "INSERT INTO finances (user_id, amount, category, description) VALUES (?, ?, ?, ?)",
        (message.from_user.id, data["amount"], data["category"], description)
    )
    conn.commit()

    await message.answer(
        f"✅ Расход добавлен:\n"
        f"Сумма: {data['amount']} ₽\n"
        f"Категория: {data['category']}\n"
        f"Описание: {description}",
        reply_markup=get_finance_kb()
    )
    await state.clear()


@dp.message(F.text == "📊 Статистика расходов")
async def show_finance_stats(message: types.Message):
    current_month = datetime.now().strftime("%Y-%m")

    cursor.execute(
        "SELECT SUM(amount) FROM finances WHERE user_id = ? AND strftime('%Y-%m', date) = ?",
        (message.from_user.id, current_month)
    )
    total = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT category, SUM(amount) FROM finances WHERE user_id = ? AND strftime('%Y-%m', date) = ? GROUP BY category",
        (message.from_user.id, current_month)
    )
    categories = cursor.fetchall()

    cursor.execute(
        "SELECT date, SUM(amount) FROM finances WHERE user_id = ? AND strftime('%Y-%m', date) = ? GROUP BY date",
        (message.from_user.id, current_month)
    )
    daily = cursor.fetchall()

    response = f"📊 Статистика расходов за {current_month}:\n\n"
    response += f"Всего потрачено: {total:.2f} ₽\n\n"

    if categories:
        response += "По категориям:\n"
        for cat, amount in categories:
            response += f"  {cat}: {amount:.2f} ₽\n"

    if daily:
        response += "\nПо дням:\n"
        for date, amount in daily:
            response += f"  {date}: {amount:.2f} ₽\n"

    await message.answer(response, reply_markup=get_finance_kb())


@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_kb())


@dp.message(F.text == "➕ Добавить задачу")
async def add_task(message: types.Message, state: FSMContext):
    await state.set_state(TaskStates.waiting_description)
    await message.answer("Введите описание задачи:", reply_markup=types.ReplyKeyboardRemove())


@dp.message(TaskStates.waiting_description)
async def get_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(TaskStates.waiting_deadline)
    await message.answer("Введите дедлайн (формат: ГГГГ-ММ-ДД ЧЧ:ММ):")


@dp.message(TaskStates.waiting_deadline)
async def get_deadline(message: types.Message, state: FSMContext):
    try:
        deadline_dt = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        now = datetime.now()

        if deadline_dt < now:
            await message.answer("❌ Нельзя устанавливать дедлайн в прошлом. Введите дату в будущем:")
            return

        await state.update_data(deadline=message.text)
        await state.set_state(TaskStates.waiting_repeat)
        await message.answer("Как часто повторять задачу?", reply_markup=repeat_kb)

    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД ЧЧ:ММ")



@dp.callback_query(F.data.startswith("repeat_"))
async def process_repeat(callback: types.CallbackQuery, state: FSMContext):
    repeat = callback.data.split("_")[1]
    data = await state.get_data()
    cursor.execute("INSERT INTO tasks (user_id, description, deadline, repeat) VALUES (?, ?, ?, ?)",
                   (callback.from_user.id, data["description"], data["deadline"], repeat))
    conn.commit()
    await callback.message.answer("Задача добавлена ✅", reply_markup=get_main_kb())
    await state.clear()
    await callback.answer()


@dp.message(F.text == "📝 Список задач")
async def list_tasks(message: types.Message):
    cursor.execute("SELECT id, description, deadline, repeat FROM tasks WHERE user_id = ?", (message.from_user.id,))
    tasks = cursor.fetchall()
    if not tasks:
        await message.answer("У вас нет задач.")
    else:
        text = "\n".join([f"{i}. {t[1]} — {t[2]} ({t[3]})" for i, t in enumerate(tasks, start=1)])
        await message.answer(text)


@dp.message(F.text == "❌ Удалить задачу")
async def delete_task(message: types.Message):
    cursor.execute("SELECT id, description FROM tasks WHERE user_id = ?", (message.from_user.id,))
    tasks = cursor.fetchall()
    if not tasks:
        await message.answer("Нет задач для удаления.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, task in enumerate(tasks, start=1):
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text=f"{i}. {task[1]}", callback_data=f"delete_{task[0]}")]
        )

    await message.answer("Выберите задачу для удаления:", reply_markup=kb)


@dp.callback_query(F.data.startswith("delete_"))
async def confirm_delete(callback: types.CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(task_id=task_id)
    await callback.message.answer("Задача выполнена?", reply_markup=completion_kb)
    await state.set_state(TaskStates.waiting_task_completion)
    await callback.answer()


@dp.callback_query(F.data.startswith("complete_"), TaskStates.waiting_task_completion)
async def process_completion(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    is_completed = callback.data.split("_")[1] == "yes"

    # Удаляем задачу
    cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, callback.from_user.id))

    # Проверяем, есть ли уже запись в stats
    cursor.execute("SELECT 1 FROM stats WHERE user_id = ?", (callback.from_user.id,))
    exists = cursor.fetchone()

    if exists:
        # Обновляем существующую запись
        if is_completed:
            cursor.execute("UPDATE stats SET completed = completed + 1 WHERE user_id = ?",
                           (callback.from_user.id,))
        else:
            cursor.execute("UPDATE stats SET uncompleted = uncompleted + 1 WHERE user_id = ?",
                           (callback.from_user.id,))
    else:
        # Создаем новую запись
        if is_completed:
            cursor.execute("INSERT INTO stats (user_id, completed, uncompleted) VALUES (?, 1, 0)",
                           (callback.from_user.id,))
        else:
            cursor.execute("INSERT INTO stats (user_id, completed, uncompleted) VALUES (?, 0, 1)",
                           (callback.from_user.id,))

    conn.commit()
    await callback.message.answer("Задача удалена.", reply_markup=get_main_kb())
    await state.clear()
    await callback.answer()


@dp.message(F.text == "✏️ Редактировать задачу")
async def start_edit(message: types.Message, state: FSMContext):
    cursor.execute("SELECT id, description FROM tasks WHERE user_id = ?", (message.from_user.id,))
    tasks = cursor.fetchall()
    if not tasks:
        await message.answer("Нет задач для редактирования.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, task in enumerate(tasks, start=1):
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text=f"{i}. {task[1]}", callback_data=f"edit_task_{task[0]}")]
        )

    await message.answer("Выберите задачу для редактирования:", reply_markup=kb)


@dp.callback_query(F.data.startswith("edit_task_"))
async def choose_field(callback: types.CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    await state.update_data(task_id=task_id)
    await callback.message.answer("Что вы хотите изменить?", reply_markup=edit_field_kb)
    await state.set_state(TaskStates.waiting_edit_field)
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_"), TaskStates.waiting_edit_field)
async def get_edit_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    await state.update_data(field=field)
    await callback.message.answer("Введите новое значение:")
    await state.set_state(TaskStates.waiting_edit_value)
    await callback.answer()


@dp.message(TaskStates.waiting_edit_value)
async def apply_edit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    field = data["field"]
    value = message.text

    if field == "deadline":
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            await message.answer("Неверный формат даты. Используйте ГГГГ-ММ-ДД ЧЧ:ММ")
            return

    if field == "repeat" and value.lower() not in ["никогда", "еженедельно"]:
        await message.answer("Допустимые значения: 'никогда' или 'еженедельно'")
        return

    cursor.execute(f"UPDATE tasks SET {field} = ? WHERE id = ? AND user_id = ?",
                   (value, task_id, message.from_user.id))
    conn.commit()
    await message.answer("Обновлено ✅", reply_markup=get_main_kb())
    await state.clear()


@dp.message(F.text == "♻️ Еженедельные задачи")
async def show_weekly(message: types.Message):
    cursor.execute("SELECT description, deadline FROM tasks WHERE user_id = ? AND repeat = 'еженедельно'",
                   (message.from_user.id,))
    tasks = cursor.fetchall()
    if not tasks:
        await message.answer("Нет еженедельных задач.")
    else:
        text = "\n".join([f"{t[0]} — {t[1]}" for t in tasks])
        await message.answer(text)


@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    # Получаем статистику выполнения задач
    cursor.execute("SELECT completed, uncompleted FROM stats WHERE user_id = ?", (message.from_user.id,))
    stats = cursor.fetchone()
    completed = stats[0] if stats else 0
    uncompleted = stats[1] if stats else 0

    # Получаем текущее количество задач
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (message.from_user.id,))
    current_tasks = cursor.fetchone()[0]

    # Получаем количество еженедельных задач
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND repeat = 'еженедельно'", (message.from_user.id,))
    weekly_tasks = cursor.fetchone()[0]

    response = (
        f"📊 Статистика задач:\n\n"
        f"✅ Выполнено: {completed}\n"
        f"❌ Не выполнено: {uncompleted}\n"
        f"📌 Всего активных задач: {current_tasks}\n"
        f"♻️ Из них еженедельных: {weekly_tasks}"
    )
    await message.answer(response)


@dp.message(F.text == "💱 Курс валют")
async def exchange_rate(message: types.Message):
    url = "https://open.er-api.com/v6/latest/RUB"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await message.answer("⚠️ Не удалось получить курс валют.")
                    return
                data = await resp.json()
                rates = data.get("rates", {})
                if not all(k in rates for k in ["USD", "EUR", "CNY", "JPY"]):
                    await message.answer("⚠️ Данные от API неполные.")
                    return

                usd = 1 / rates["USD"]
                eur = 1 / rates["EUR"]
                cny = 1 / rates["CNY"]
                jpy = 1 / rates["JPY"]

                await message.answer(
                    f"💱 Курсы валют:\n\n"
                    f"🇺🇸 USD: {usd:.4f}\n"
                    f"🇪🇺 EUR: {eur:.4f}\n"
                    f"🇨🇳 CNY: {cny:.4f}\n"
                    f"🇯🇵 JPY: {jpy:.4f}"
                )
        except Exception as e:
            await message.answer("❌ Ошибка при получении курса валют.")
            print("Currency error:", e)


@dp.message(F.text == "🌦️ Погода")
async def weather(message: types.Message):
    await message.answer("Выберите город:", reply_markup=weather_cities_kb)


@dp.callback_query(F.data.startswith("weather_"))
async def weather_city(callback: types.CallbackQuery, state: FSMContext):
    city = callback.data.split("_")[1]
    if city == "other":
        await callback.message.answer("Введите название города:")
        await state.set_state(TaskStates.waiting_weather_city)
        await callback.answer()
        return

    await process_weather_request(callback.message, city)
    await callback.answer()


@dp.message(TaskStates.waiting_weather_city)
async def handle_custom_weather_city(message: types.Message, state: FSMContext):
    city = message.text.strip()
    await process_weather_request(message, city)
    await state.clear()


async def process_weather_request(message: types.Message, city: str):
    url = f"https://wttr.in/{city}?format=3"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                text = await resp.text()
                await message.answer(f"🌤️ Погода: {text}", reply_markup=get_main_kb())
            else:
                await message.answer("Город не найден.", reply_markup=get_main_kb())


@dp.message(F.text == "📰 Новости")
async def news(message: types.Message):
    feed = feedparser.parse("https://rssexport.rbc.ru/rbcnews/news/30/full.rss")
    entries = feed.entries[:3]
    response = "\n\n".join([f"🗞 {e.title}\n{e.link}" for e in entries])
    await message.answer(response)


# Обработчик для любых других сообщений
@dp.message()
async def handle_other_messages(message: types.Message):
    await message.answer("Пожалуйста, используйте кнопки меню.", reply_markup=get_main_kb())


async def reminder_loop():
    while True:
        now = datetime.now()
        next_hour = now + timedelta(hours=1)

        # Обычные задачи
        cursor.execute("""
            SELECT id, user_id, description FROM tasks
            WHERE reminded = 0 AND repeat = 'никогда' AND datetime(deadline) BETWEEN ? AND ?
        """, (now.strftime("%Y-%m-%d %H:%M"), next_hour.strftime("%Y-%m-%d %H:%M")))

        for task_id, user_id, desc in cursor.fetchall():
            try:
                await bot.send_message(user_id, f"⏰ Напоминание: через час дедлайн задачи:\n<b>{desc}</b>",
                                       parse_mode="HTML")
                cursor.execute("UPDATE tasks SET reminded = 1 WHERE id = ?", (task_id,))
            except:
                continue

        # Повторяющиеся еженедельные задачи
        cursor.execute("""
            SELECT id, user_id, description FROM tasks
            WHERE repeat = 'еженедельно' AND reminded = 0 AND strftime('%w %H:%M', deadline) = strftime('%w %H:%M', ?)
        """, (next_hour.strftime("%Y-%m-%d %H:%M"),))

        for task_id, user_id, desc in cursor.fetchall():
            try:
                await bot.send_message(user_id, f"🔁 Напоминание: через час еженедельная задача:\n<b>{desc}</b>",
                                       parse_mode="HTML")
                cursor.execute("UPDATE tasks SET reminded = 1 WHERE id = ?", (task_id,))
            except:
                continue

        # Обнуляем напоминания для задач, дата которых прошла (чтобы сработало на следующей неделе)
        cursor.execute("""
            UPDATE tasks SET reminded = 0 WHERE repeat = 'еженедельно' AND datetime(deadline) < datetime('now')
        """)
        conn.commit()

        await asyncio.sleep(60)

async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())