import asyncio
import logging
import os
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

# ================= CONFIG =================

TOKEN = "PASTE_YOUR_TOKEN_HERE"

OWNERS = {6279994177, 5857555465}

BASE_URL = "https://telega6752.onrender.com"
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "secret123"

PORT = int(os.getenv("PORT", 10000))

# ================= INIT =================

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ================= DB =================

conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER DEFAULT 0,
    card TEXT DEFAULT '',
    room TEXT DEFAULT ''
)
""")

conn.commit()

# ================= HELPERS =================

def is_owner(uid: int):
    return uid in OWNERS

def add_user(uid: int):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (uid,))
    conn.commit()

# ================= COMMANDS =================

@dp.message(F.text == "/start")
async def start(m: Message):
    add_user(m.from_user.id)
    await m.answer("🤖 Bot V4 webhook online")

# -------- CREATE TOURNAMENT --------

@dp.message(F.text.startswith("/create"))
async def create(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("Формат: /create 1")

    number = int(parts[1])

    cursor.execute("INSERT OR IGNORE INTO tournaments(number) VALUES (?)", (number,))
    conn.commit()

    await m.answer(f"✅ Турнир {number} создан")

# -------- LIST --------

@dp.message(F.text == "/list")
async def list_t(m: Message):
    if not is_owner(m.from_user.id):
        return

    data = cursor.execute("SELECT number, price, card, room FROM tournaments").fetchall()

    if not data:
        return await m.answer("❌ Нет турниров")

    text = "📋 Турниры:\n\n"

    for t in data:
        text += f"🎮 {t[0]}\n💰 {t[1]}\n💳 {t[2]}\n🎮 {t[3]}\n\n"

    await m.answer(text)

# -------- PRICE --------

@dp.message(F.text.startswith("/price"))
async def price(m: Message):
    if not is_owner(m.from_user.id):
        return

    _, number, value = m.text.split()

    cursor.execute(
        "UPDATE tournaments SET price=? WHERE number=?",
        (int(value), int(number))
    )
    conn.commit()

    await m.answer("💰 Цена обновлена")

# -------- CARD --------

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)
    number = int(parts[1])
    value = parts[2]

    cursor.execute(
        "UPDATE tournaments SET card=? WHERE number=?",
        (value, number)
    )
    conn.commit()

    await m.answer("💳 Карта обновлена")

# -------- ROOM --------

@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)
    number = int(parts[1])
    link = parts[2]

    cursor.execute(
        "UPDATE tournaments SET room=? WHERE number=?",
        (link, number)
    )
    conn.commit()

    await m.answer("🎮 Комната обновлена")

# -------- SEND (BROADCAST) --------

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

async def handle(request):
    data = await request.json()

    update = dp.update.model_validate(data)
    await dp.feed_update(bot, update)

    return web.Response(text="ok")

async def health(request):
    return web.Response(text="bot alive")

async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(f"{BASE_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)

# ================= APP =================

async def main():
    logging.basicConfig(level=logging.INFO)

    app = web.Application()

    app.router.add_post(WEBHOOK_PATH, handle)
    app.router.add_get("/", health)

    await on_startup()

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("BOT RUNNING (V4 WEBHOOK)")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
