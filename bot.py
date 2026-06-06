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
BASE_URL = os.getenv("BASE_URL")  # https://your-app.onrender.com
OWNERS = set(map(int, filter(str.isdigit, os.getenv("OWNERS", "").split(","))))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = BASE_URL + WEBHOOK_PATH

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
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

def is_owner(user_id: int) -> bool:
    return user_id in OWNERS

def safe_int(x):
    try:
        return int(x)
    except:
        return None

# ================= COMMANDS =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()
    await m.answer("🤖 Бот работает")

# ---------- LIST ----------

@dp.message(F.text.startswith("/list"))
async def list_t(m: Message):
    rows = cursor.execute("SELECT number, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Турниров нет")

    text = "🎮 Турниры:\n\n"
    for n, p in rows:
        text += f"#{n} — {p}₽\n"

    await m.answer(text)

# ---------- JOIN ----------

@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    parts = m.text.split()

    if len(parts) < 2:
        return await m.answer("Формат: /join 1")

    number = safe_int(parts[1])
    if number is None:
        return await m.answer("Неверный номер")

    tour = cursor.execute(
        "SELECT price, card, room FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("Турнир не найден")

    price, card, room = tour

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
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

    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer("Формат: /price 1 100")

    number = safe_int(parts[1])
    value = safe_int(parts[2])

    if None in (number, value):
        return await m.answer("Ошибка данных")

    cursor.execute(
        "UPDATE tournaments SET price=? WHERE number=?",
        (value, number)
    )
    conn.commit()

    await m.answer("💰 Обновлено")

# ---------- CARD ----------

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Формат: /card 1 text")

    number = safe_int(parts[1])
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
    if len(parts) < 3:
        return await m.answer("Формат: /room 1 link")

    number = safe_int(parts[1])
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

    for (uid,) in users:
        try:
            await bot.send_message(uid, text)
        except:
            pass

    await m.answer("📢 Отправлено")

# ---------- DEBUG ----------

@dp.message(F.text == "/debug")
async def debug(m: Message):
    await m.answer("бот работает ✅")

# ================= WEBHOOK =================

async def handle(request):
    try:
        data = await request.json()

        print("UPDATE:", data)

        update = Update(**data)

        await dp.feed_update(bot, update)

        return web.Response(text="ok")

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return web.Response(text="error", status=500)

async def on_startup(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook set:", WEBHOOK_URL)

async def on_shutdown(app):
    await bot.session.close()

app = web.Application()
app.router.add_post("/webhook", handle)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# ================= MAIN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
