import asyncio
import logging
import sqlite3
import os

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")  # В Render → Environment Variables
WEBHOOK_PATH = "/webhook"
BASE_URL = os.getenv("BASE_URL")  # например https://xxxx.onrender.com

OWNERS = [123456789, 987654321]  # <-- поставь свои 2 ID

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# ================= DB =================

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    card TEXT,
    room TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")
conn.commit()

# ================= HELPERS =================

def is_owner(user_id: int):
    return user_id in OWNERS

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()
    await m.answer("👋 Бот работает")

# ================= LIST =================

@dp.message(F.text.startswith("/list"))
async def list_tournaments(m: Message):
    rows = cursor.execute("SELECT number, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("❌ Турниров нет")

    text = "📋 Турниры:\n\n"
    for r in rows:
        text += f"#{r[0]} — {r[1]}₽\n"

    await m.answer(text)

# ================= JOIN =================

@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    parts = m.text.split()

    if len(parts) < 2:
        return await m.answer("Формат: /join 1")

    number = int(parts[1])

    tour = cursor.execute(
        "SELECT price, card, room FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("❌ Турнир не найден")

    price, card, room = tour

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer(
        f"💰 Цена: {price}\n"
        f"💳 Карта: {card}\n"
        f"🎮 Комната: {room}"
    )

# ================= CREATE =================

@dp.message(F.text.startswith("/create"))
async def create(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()

    if len(parts) < 3:
        return await m.answer("Формат: /create 1 100")

    number = int(parts[1])
    price = int(parts[2])

    cursor.execute(
        "INSERT OR REPLACE INTO tournaments(number, price, card, room) VALUES (?, ?, '', '')",
        (number, price)
    )
    conn.commit()

    await m.answer("✅ Турнир создан")

# ================= PRICE =================

@dp.message(F.text.startswith("/price"))
async def price(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()

    number = int(parts[1])
    value = int(parts[2])

    cursor.execute("UPDATE tournaments SET price=? WHERE number=?", (value, number))
    conn.commit()

    await m.answer("💰 Цена обновлена")

# ================= CARD =================

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)

    number = int(parts[1])
    value = parts[2]

    cursor.execute("UPDATE tournaments SET card=? WHERE number=?", (value, number))
    conn.commit()

    await m.answer("💳 Карта обновлена")

# ================= ROOM =================

@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)

    number = int(parts[1])
    link = parts[2]

    cursor.execute("UPDATE tournaments SET room=? WHERE number=?", (link, number))
    conn.commit()

    await m.answer("🎮 Комната обновлена")

# ================= SEND =================

@dp.message(F.text.startswith("/send"))
async def send_all(m: Message):
    if not is_owner(m.from_user.id):
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

async def webhook_handler(request: web.Request):
    data = await request.json()

    update = Update.model_validate(data)
    await dp.feed_update(bot, update)

    return web.Response(text="OK")

async def on_startup(app):
    await bot.set_webhook(f"{BASE_URL}{WEBHOOK_PATH}")
    logging.info("Webhook set")

# ================= APP =================

def create_app():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    app.on_startup.append(on_startup)
    return app

# ================= RUN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    app = create_app()
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
