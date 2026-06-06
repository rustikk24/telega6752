import asyncio
import logging
import os
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ================= ENV =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
OWNERS_RAW = os.getenv("OWNERS", "")

OWNERS = set()

for x in OWNERS_RAW.split(","):
    if x.strip().isdigit():
        OWNERS.add(int(x.strip()))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# ================= DB =================

conn = sqlite3.connect("db.sqlite3")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    card TEXT,
    room TEXT
)
""")

conn.commit()

# ================= HELPERS =================

def is_owner(user_id: int) -> bool:
    return user_id in OWNERS

# ================= COMMANDS =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()
    await m.answer("🤖 Бот активен")

# ---------- LIST ----------

@dp.message(F.text.startswith("/list"))
async def list_tournaments(m: Message):
    rows = cursor.execute("SELECT number, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Турниров нет")

    text = "🎮 Турниры:\n\n"
    for r in rows:
        text += f"#{r[0]} — {r[1]}₽\n"

    await m.answer(text)

# ---------- JOIN ----------

@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    parts = m.text.split()

    if len(parts) < 2:
        return await m.answer("Используй: /join 1")

    number = int(parts[1])

    tour = cursor.execute(
        "SELECT price, card, room FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("Турнир не найден")

    price, card, room = tour

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer(
        f"💰 Цена: {price}\n"
        f"💳 Карта: {card}\n"
        f"🎮 Комната: {room}"
    )

# ---------- PRICE ----------

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

    await m.answer("💰 Обновлено")

# ---------- CARD ----------

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

    await m.answer("💳 Обновлено")

# ---------- ROOM ----------

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

    await m.answer("🎮 Обновлено")

# ---------- SEND ----------

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

    await m.answer("📢 Отправлено")

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook set")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

app = web.Application()
app.router.add_post(WEBHOOK_PATH, handle)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# ================= MAIN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
