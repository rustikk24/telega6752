import asyncio
import logging
import sqlite3
import os

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.filters import CommandStart

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.onrender.com
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_PATH = "/webhook"

if not TOKEN:
    raise Exception("BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ================= ADMINS =================

ADMINS = {6279994177, 5857555465}

def is_admin(user_id: int):
    return user_id in ADMINS

# ================= DB =================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    date TEXT,
    time TEXT,
    price INTEGER DEFAULT 0,
    card TEXT DEFAULT '',
    room TEXT DEFAULT ''
)
""")

conn.commit()

# ================= START =================

@dp.message(CommandStart())
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()
    await m.answer("👋 Бот турниров онлайн")

# ================= TOURNAMENT CREATE =================

tour_state = {}

@dp.message(F.text == "/tour")
async def tour(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("❌ Нет доступа")

    tour_state[m.from_user.id] = {}
    await m.answer("🏆 Название турнира?")

@dp.message()
async def tour_flow(m: Message):
    if m.from_user.id not in tour_state:
        return

    data = tour_state[m.from_user.id]

    if "name" not in data:
        data["name"] = m.text
        return await m.answer("📅 Дата (DD.MM.YYYY)")

    if "date" not in data:
        data["date"] = m.text
        return await m.answer("⏰ Время (HH:MM)")

    if "time" not in data:
        data["time"] = m.text
        return await m.answer("💰 Цена")

    if "price" not in data:
        try:
            data["price"] = int(m.text)
        except:
            return await m.answer("❌ Введи число")

        cursor.execute("""
        INSERT INTO tournaments (name, date, time, price)
        VALUES (?, ?, ?, ?)
        """, (data["name"], data["date"], data["time"], data["price"]))

        conn.commit()
        del tour_state[m.from_user.id]

        return await m.answer("✅ Турнир создан")

# ================= LIST =================

@dp.message(F.text == "/list")
async def list_t(m: Message):
    rows = cursor.execute("SELECT number, name, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Нет турниров")

    text = "🏆 Турниры:\n\n"
    for r in rows:
        text += f"#{r[0]} | {r[1]} | 💰 {r[2]}\n"

    await m.answer(text)

# ================= JOIN =================

@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    try:
        number = int(m.text.split()[1])
    except:
        return await m.answer("Формат: /join 1")

    tour = cursor.execute(
        "SELECT price, card, room FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("❌ Турнир не найден")

    price, card, room = tour

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer(
        f"🎮 Турнир #{number}\n"
        f"💰 Цена: {price}\n"
        f"💳 Карта: {card}\n"
        f"🚪 Комната: {room}"
    )

# ================= PRICE =================

@dp.message(F.text.startswith("/price"))
async def price(m: Message):
    if not is_admin(m.from_user.id):
        return

    try:
        _, number, value = m.text.split()
        cursor.execute("UPDATE tournaments SET price=? WHERE number=?", (int(value), int(number)))
        conn.commit()
        await m.answer("💰 Цена обновлена")
    except:
        await m.answer("Формат: /price 1 100")

# ================= CARD =================

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_admin(m.from_user.id):
        return

    try:
        _, number, value = m.text.split(maxsplit=2)
        cursor.execute("UPDATE tournaments SET card=? WHERE number=?", (value, int(number)))
        conn.commit()
        await m.answer("💳 Карта обновлена")
    except:
        await m.answer("Формат: /card 1 текст")

# ================= ROOM =================

@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_admin(m.from_user.id):
        return

    try:
        _, number, link = m.text.split(maxsplit=2)
        cursor.execute("UPDATE tournaments SET room=? WHERE number=?", (link, int(number)))
        conn.commit()
        await m.answer("🎮 Комната обновлена")
    except:
        await m.answer("Формат: /room 1 ссылка")

# ================= SEND =================

@dp.message(F.text.startswith("/send"))
async def send_all(m: Message):
    if not is_admin(m.from_user.id):
        return

    text = m.text.replace("/send", "").strip()

    users = cursor.execute("SELECT user_id FROM users").fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], text)
        except:
            pass

    await m.answer("📢 Рассылка отправлена")

# ================= WEBHOOK =================

async def handle(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response()

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    print("Webhook set:", WEBHOOK_URL + WEBHOOK_PATH)

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

def create_app():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

# ================= MAIN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), port=PORT)