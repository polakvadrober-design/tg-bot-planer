import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from datetime import datetime, timedelta
import re

# === НАСТРОЙКИ ===
API_TOKEN = '0' 

# === ГЛОБАЛЬНЫЕ ОБЪЕКТЫ ===
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# === ХРАНЕНИЕ СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЕЙ ===
user_states = {}  # user_id → {mode: ..., task_id: ...}

# === КНОПКА "ГЛАВНОЕ МЕНЮ" ===
def get_main_menu_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
    ])

# === ИНИЦИАЛИЗАЦИЯ БД ===
async def init_db():
    async with aiosqlite.connect("tasks.db") as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_time TIMESTAMP
            )
        ''')
        await db.commit()

# === ФУНКЦИИ РАБОТЫ С ЗАДАЧАМИ ===
async def add_task(user_id: int, task: str, reminder_time=None):
    async with aiosqlite.connect("tasks.db") as db:
        await db.execute(
            "INSERT INTO tasks (user_id, task, reminder_time) VALUES (?, ?, ?)",
            (user_id, task, reminder_time)
        )
        await db.commit()

async def get_tasks(user_id: int):
    async with aiosqlite.connect("tasks.db") as db:
        async with db.execute(
            "SELECT id, task, reminder_time FROM tasks WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()

async def delete_task(task_id: int):
    async with aiosqlite.connect("tasks.db") as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
        return True  # Упрощённо

async def edit_task(task_id: int, new_task: str, new_reminder=None):
    async with aiosqlite.connect("tasks.db") as db:
        await db.execute(
            "UPDATE tasks SET task = ?, reminder_time = ? WHERE id = ?",
            (new_task, new_reminder, task_id)
        )
        await db.commit()
        return True

# === ПРОВЕРКА НАПОМИНАНИЙ (с автоматическим удалением) ===
async def check_reminders():
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        async with aiosqlite.connect("tasks.db") as db:
            async with db.execute(
                "SELECT id, user_id, task FROM tasks WHERE reminder_time IS NOT NULL AND reminder_time <= ?",
                (now,)
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    task_id, user_id, task = row
                    try:
                        # Отправляем напоминание + кнопка "Выполнено"
                        await bot.send_message(
                            user_id,
                            f"⏰ Напоминание: {task}\n\n"
                            "Если уже сделал — нажми кнопку ниже.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="✅ Я сделал!", callback_data=f"done_{task_id}")]
                            ])
                        )
                        # Удаляем задачу из базы
                        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                        await db.commit()
                    except Exception as e:
                        print(f"Ошибка при отправке напоминания {user_id}: {e}")

# === КНОПКИ ===
def get_main_menu_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои задачи", callback_data="my_tasks")],
        [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")]
    ])

def get_tasks_keyboard(tasks):
    buttons = []
    for task_id, task, reminder in tasks:
        prefix = "⏰ " if reminder else ""
        short_text = task if len(task) <= 30 else task[:27] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"{prefix}{short_text}",
            callback_data=f"task_{task_id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_task_actions(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{task_id}")],
        [InlineKeyboardButton(text="✅ Выполнить", callback_data=f"done_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_tasks")]
    ])

# === ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_states.pop(message.from_user.id, None)
    await message.answer(
        "👋 Привет! Я — твой личный планер.\n\n"
        "⏰ Напомню вовремя — «в 18:00» или «через 10 минут»\n"
        "✅ Позволю закрыть задачу со словами «я сделал!»\n"
        "🧹 Удалю старое, чтобы не мешало\n\n"
        "Ты просто пиши, что нужно сделать — остальное возьму на себя.\n\n"
        "Начнём? Жми кнопку или напиши первую задачу 👇",
        reply_markup=get_main_menu_inline()
    )

@dp.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery):
    try:
        await callback.message.edit_text("Выбери действие:", reply_markup=get_main_menu_inline())
    except Exception:
        await callback.message.edit_text("Выбери действие:")
        await callback.message.edit_reply_markup(reply_markup=get_main_menu_inline())
    await callback.answer()

@dp.callback_query(F.data == "my_tasks")
async def show_tasks(callback: CallbackQuery):
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.edit_text(
            "У тебя нет активных задач.",
            reply_markup=get_main_menu_button()
        )
    else:
        await callback.message.edit_text(
            "📌 Твои задачи:",
            reply_markup=get_tasks_keyboard(tasks)
        )
    await callback.answer()

@dp.callback_query(F.data.startswith("task_"))
async def show_task_actions(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    tasks = await get_tasks(callback.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)
    if not task:
        await callback.answer("❌ Задача не найдена.")
        return

    task_text = task[1]
    status = "⏰ Будет напоминание" if task[2] else "🕒 Без напоминания"
    await callback.message.edit_text(
        f"📋 *{task_text}*\n\n{status}",
        parse_mode="Markdown",
        reply_markup=get_task_actions(task_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_"))
async def confirm_delete(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    await callback.message.edit_text(
        "🗑 Удалить задачу безвозвратно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_delete_{task_id}")],
            [InlineKeyboardButton(text="❌ Нет", callback_data=f"task_{task_id}")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def do_delete(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    await delete_task(task_id)
    await callback.message.edit_text(
        "🗑 Задача удалена.",
        reply_markup=get_main_menu_button()
    )
    await callback.answer()

@dp.callback_query(F.data == "add_task")
async def add_task_prompt(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states[user_id] = {"mode": "awaiting_new_task"}
    await callback.message.edit_text(
        "✍️ Напиши новую задачу.\n\n"
        "Можно с временем:\n"
        "• *Купить хлеб в 18:30*\n"
        "• *Через 10 минут*\n"
        "• *Завтра в 9:00*",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_"))
async def start_edit(callback: CallbackQuery):
    user_id = callback.from_user.id
    task_id = int(callback.data.split("_")[1])
    user_states[user_id] = {"mode": "editing", "task_id": task_id}
    await callback.message.edit_text("✏️ Напиши новое описание:")
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def complete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    success = await delete_task(task_id)
    if success:
        await callback.message.edit_text(
            "🎉 Отлично! Задача завершена и удалена.\n"
            "Ты молодец! 💪",
            reply_markup=get_main_menu_button()
        )
    else:
        await callback.message.edit_text(
            "❌ Задача уже была удалена.",
            reply_markup=get_main_menu_button()
        )
    await callback.answer()

# === ОБРАБОТКА ТЕКСТА ===
@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.get(user_id)

    # === РЕДАКТИРОВАНИЕ ===
    if state and state["mode"] == "editing":
        task_id = state["task_id"]
        new_text = text

        # Парсинг времени
        new_reminder = None
        time_match = re.search(r'в (\d{1,2}):(\d{2})', new_text)
        tomorrow_match = "завтра" in new_text
        minutes_match = re.search(r'через (\d+) минут', new_text)

        if time_match:
            hour, minute = map(int, time_match.groups())
            now = datetime.now()
            reminder = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if tomorrow_match:
                reminder += timedelta(days=1)
            elif reminder < now:
                reminder += timedelta(days=1)
            new_reminder = reminder
            new_text = re.sub(r'в \d{1,2}:\d{2}( завтра)?', '', new_text).strip()

        elif minutes_match:
            minutes = int(minutes_match.group(1))
            new_reminder = datetime.now() + timedelta(minutes=minutes)
            new_text = re.sub(r'через \d+ минут', '', new_text).strip()

        if not new_text:
            await message.reply("❌ Описание не может быть пустым.", reply_markup=get_main_menu_button())
            user_states.pop(user_id, None)
            return

        if await edit_task(task_id, new_text, new_reminder):
            status = f"\n⏰ Напомню {new_reminder.strftime('%d.%m в %H:%M')}" if new_reminder else ""
            await message.reply(f"✅ Обновлено:\n*{new_text}*{status}", parse_mode="Markdown", reply_markup=get_main_menu_button())
        else:
            await message.reply("❌ Ошибка при редактировании.", reply_markup=get_main_menu_button())

        user_states.pop(user_id, None)
        return

    # === ДОБАВЛЕНИЕ ===
    if state and state["mode"] == "awaiting_new_task":
        reminder_time = None
        time_match = re.search(r'в (\d{1,2}):(\d{2})', text)
        tomorrow_match = "завтра" in text
        minutes_match = re.search(r'через (\d+) минут', text)

        if time_match:
            hour, minute = map(int, time_match.groups())
            now = datetime.now()
            reminder = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if tomorrow_match:
                reminder += timedelta(days=1)
            elif reminder < now:
                reminder += timedelta(days=1)
            reminder_time = reminder
            text = re.sub(r'в \d{1,2}:\d{2}( завтра)?', '', text).strip()

        elif minutes_match:
            minutes = int(minutes_match.group(1))
            reminder_time = datetime.now() + timedelta(minutes=minutes)
            text = re.sub(r'через \d+ минут', '', text).strip()

        if not text:
            await message.reply("❌ Текст задачи не может быть пустым.", reply_markup=get_main_menu_button())
            user_states.pop(user_id, None)
            return

        await add_task(user_id, text, reminder_time)
        if reminder_time:
            await message.reply(
                f"✅ Задача добавлена: *{text}*\n⏰ Напомню {reminder_time.strftime('%d.%m в %H:%M')}",
                parse_mode="Markdown",
                reply_markup=get_main_menu_button()
            )
        else:
            await message.reply(
                f"✅ Задача добавлена: *{text}*",
                parse_mode="Markdown",
                reply_markup=get_main_menu_button()
            )

        user_states.pop(user_id, None)
        return

    # === ОБЫЧНОЕ ДОБАВЛЕНИЕ (если не в режиме) ===
    reminder_time = None
    time_match = re.search(r'в (\d{1,2}):(\d{2})', text)
    tomorrow_match = "завтра" in text
    minutes_match = re.search(r'через (\d+) минут', text)

    if time_match:
        hour, minute = map(int, time_match.groups())
        now = datetime.now()
        reminder = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow_match:
            reminder += timedelta(days=1)
        elif reminder < now:
            reminder += timedelta(days=1)
        reminder_time = reminder
        text = re.sub(r'в \d{1,2}:\d{2}( завтра)?', '', text).strip()

    elif minutes_match:
        minutes = int(minutes_match.group(1))
        reminder_time = datetime.now() + timedelta(minutes=minutes)
        text = re.sub(r'через \d+ минут', '', text).strip()

    if not text:
        await message.reply("❌ Текст задачи не может быть пустым.", reply_markup=get_main_menu_button())
        return

    await add_task(user_id, text, reminder_time)
    if reminder_time:
        await message.reply(
            f"✅ Добавлено: *{text}*\n⏰ Напомню {reminder_time.strftime('%d.%m в %H:%M')}",
            parse_mode="Markdown",
            reply_markup=get_main_menu_button()
        )
    else:
        await message.reply(
            f"✅ Добавлено: *{text}*",
            parse_mode="Markdown",
            reply_markup=get_main_menu_button()
        )

# === ЗАПУСК ===
async def main():
    await init_db()
    asyncio.create_task(check_reminders())  # Фоновая проверка
    print("✅ Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())