import sqlite3
import threading
import time
import re
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

API_TOKEN = '0'

bot = telebot.TeleBot(API_TOKEN, parse_mode="Markdown")
user_states = {}

def init_db():
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reminder_time TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_task(user_id, task, reminder_time=None):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks (user_id, task, reminder_time) VALUES (?, ?, ?)",
                (user_id, task, reminder_time))
    conn.commit()
    conn.close()

def get_tasks(user_id):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("SELECT id, task, reminder_time FROM tasks WHERE user_id = ? ORDER BY created_at",
                (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_task(task_id):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return True

def edit_task(task_id, new_task, new_reminder=None):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET task = ?, reminder_time = ? WHERE id = ?",
                (new_task, new_reminder, task_id))
    conn.commit()
    conn.close()
    return True

def get_main_menu_button():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🏠 Главное меню", callback_data="back"))
    return kb

def get_main_menu_inline():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks"))
    kb.add(InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task"))
    return kb

def get_tasks_keyboard(tasks):
    kb = InlineKeyboardMarkup()
    for task_id, task, reminder in tasks:
        prefix = "⏰ " if reminder else ""
        short_text = task if len(task) <= 30 else task[:27] + "..."
        kb.add(InlineKeyboardButton(f"{prefix}{short_text}", callback_data=f"task_{task_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    return kb

def get_task_actions(task_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{task_id}"))
    kb.add(InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{task_id}"))
    kb.add(InlineKeyboardButton("✅ Выполнить", callback_data=f"done_{task_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="my_tasks"))
    return kb

def parse_time(text):
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

    return text, reminder_time

def check_reminders():
    while True:
        time.sleep(60)
        now = datetime.now()
        conn = sqlite3.connect("tasks.db")
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, task FROM tasks WHERE reminder_time IS NOT NULL AND reminder_time <= ?",
                    (now,))
        rows = cur.fetchall()

        for task_id, user_id, task in rows:
            try:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("✅ Я сделал!", callback_data=f"done_{task_id}"))
                bot.send_message(user_id, f"⏰ Напоминание: {task}\n\nЕсли уже сделал — нажми кнопку ниже.", reply_markup=kb)
                cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
            except:
                pass

        conn.close()

@bot.message_handler(commands=["start"])
def start(message):
    user_states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я — твой личный планер.\n\n"
        "Начнём? Жми кнопку или напиши первую задачу 👇",
        reply_markup=get_main_menu_inline()
    )

@bot.callback_query_handler(func=lambda c: c.data == "back")
def go_back(call):
    bot.edit_message_text("Выбери действие:",
                          call.message.chat.id,
                          call.message.message_id,
                          reply_markup=get_main_menu_inline())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "my_tasks")
def show_tasks(call):
    tasks = get_tasks(call.from_user.id)
    if not tasks:
        bot.edit_message_text("У тебя нет активных задач.",
                              call.message.chat.id,
                              call.message.message_id,
                              reply_markup=get_main_menu_button())
    else:
        bot.edit_message_text("📌 Твои задачи:",
                              call.message.chat.id,
                              call.message.message_id,
                              reply_markup=get_tasks_keyboard(tasks))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("task_"))
def show_task(call):
    task_id = int(call.data.split("_")[1])
    tasks = get_tasks(call.from_user.id)
    task = next((t for t in tasks if t[0] == task_id), None)

    if not task:
        bot.answer_callback_query(call.id, "Задача не найдена")
        return

    status = "⏰ Будет напоминание" if task[2] else "🕒 Без напоминания"

    bot.edit_message_text(
        f"📋 *{task[1]}*\n\n{status}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_task_actions(task_id)
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("delete_"))
def confirm_delete(call):
    task_id = int(call.data.split("_")[1])
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Да", callback_data=f"confirm_delete_{task_id}"))
    kb.add(InlineKeyboardButton("❌ Нет", callback_data=f"task_{task_id}"))
    bot.edit_message_text("🗑 Удалить задачу безвозвратно?",
                          call.message.chat.id,
                          call.message.message_id,
                          reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_delete_"))
def do_delete(call):
    task_id = int(call.data.split("_")[2])
    delete_task(task_id)
    bot.edit_message_text("🗑 Задача удалена.",
                          call.message.chat.id,
                          call.message.message_id,
                          reply_markup=get_main_menu_button())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "add_task")
def add_task_prompt(call):
    user_states[call.from_user.id] = {"mode": "awaiting_new_task"}
    bot.edit_message_text(
        "✍️ Напиши новую задачу.\n\n"
        "Можно с временем.",
        call.message.chat.id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def start_edit(call):
    task_id = int(call.data.split("_")[1])
    user_states[call.from_user.id] = {"mode": "editing", "task_id": task_id}
    bot.edit_message_text("✏️ Напиши новое описание:",
                          call.message.chat.id,
                          call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("done_"))
def complete_task(call):
    task_id = int(call.data.split("_")[1])
    delete_task(task_id)
    bot.edit_message_text("🎉 Отлично! Задача завершена и удалена.",
                          call.message.chat.id,
                          call.message.message_id,
                          reply_markup=get_main_menu_button())
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.get(user_id)

    if state and state["mode"] == "editing":
        task_id = state["task_id"]
        text, reminder_time = parse_time(text)

        if not text:
            bot.send_message(message.chat.id, "❌ Описание не может быть пустым.", reply_markup=get_main_menu_button())
            user_states.pop(user_id, None)
            return

        edit_task(task_id, text, reminder_time)

        msg = f"✅ Обновлено:\n*{text}*"
        if reminder_time:
            msg += f"\n⏰ Напомню {reminder_time.strftime('%d.%m в %H:%M')}"
        bot.send_message(message.chat.id, msg, reply_markup=get_main_menu_button())
        user_states.pop(user_id, None)
        return

    if state and state["mode"] == "awaiting_new_task":
        text, reminder_time = parse_time(text)

        if not text:
            bot.send_message(message.chat.id, "❌ Текст задачи не может быть пустым.", reply_markup=get_main_menu_button())
            user_states.pop(user_id, None)
            return

        add_task(user_id, text, reminder_time)

        msg = f"✅ Задача добавлена: *{text}*"
        if reminder_time:
            msg += f"\n⏰ Напомню {reminder_time.strftime('%d.%m в %H:%M')}"
        bot.send_message(message.chat.id, msg, reply_markup=get_main_menu_button())
        user_states.pop(user_id, None)
        return

    text, reminder_time = parse_time(text)

    if not text:
        bot.send_message(message.chat.id, "❌ Текст задачи не может быть пустым.", reply_markup=get_main_menu_button())
        return

    add_task(user_id, text, reminder_time)

    msg = f"✅ Добавлено: *{text}*"
    if reminder_time:
        msg += f"\n⏰ Напомню {reminder_time.strftime('%d.%m в %H:%M')}"
    bot.send_message(message.chat.id, msg, reply_markup=get_main_menu_button())

if __name__ == "__main__":
    init_db()
    threading.Thread(target=check_reminders, daemon=True).start()
    print("✅ Бот запущен!")
    bot.infinity_polling()
