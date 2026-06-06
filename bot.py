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
OWNERS = set(map(int, os.getenv("OWNERS", "").split(","))) if os.getenv("OWNERS") else set()

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


# ================= USER COMMANDS =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer("🤖 Бот активен")


@dp.message(F.text.startswith("/list"))
async def list_tournaments(m: Message):
    rows = cursor.execute("SELECT number, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Турниров нет")

    text = "🎮 Турниры:\n\n"
    for r in rows:
        text += f"#{r[0]} — {r[1]}₽\n"

    await m.answer(text)


@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    parts = m.text.split()

    if len(parts) < 2:
        return await m.answer("Используй: /join 1")

    number = int(parts[1])

    tour = cursor.execute(
        "SELECT price, card FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("Турнир не найден")

    price, card = tour

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer(
        f"💰 Цена: {price}\n"
        f"💳 Карта: {card}\n\n"
        f"📌 После оплаты вы получите руму"
    )


# ================= OWNER COMMANDS =================

@dp.message(F.text.startswith("/create"))
async def create(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)

    if len(parts) < 3:
        return await m.answer("Формат: /create 1 100")

    number = int(parts[1])
    price = int(parts[2])

    cursor.execute(
        "INSERT OR REPLACE INTO tournaments (number, price, card, room) VALUES (?, ?, ?, ?)",
        (number, price, "", "")
    )
    conn.commit()

    await m.answer(f"🎮 Турнир #{number} создан")


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


@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)

    number = int(parts[1])
    link = parts[2]

    cursor.execute("UPDATE tournaments SET room=? WHERE number=?", (link, number))
    conn.commit()

    await m.answer("🎮 Рума сохранена (скрыта)")


@dp.message(F.text.startswith("/give"))
async def give_room(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()

    if len(parts) < 3:
        return await m.answer("Формат: /give user_id 1")

    user_id = int(parts[1])
    number = int(parts[2])

    tour = cursor.execute(
        "SELECT room FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour or not tour[0]:
        return await m.answer("Рума не найдена")

    await bot.send_message(user_id, f"🎮 Ваша румa:\n\n{tour[0]}")

    await m.answer("✅ Рума отправлена")


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
    try:
        data = await request.json()
        update = Update.model_validate(data)

        await dp.feed_update(bot, update)

        return web.Response(text="ok")

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return web.Response(text="error", status=500)


async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook set:", WEBHOOK_URL)


async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()


app = web.Application()
app.router.add_post("/webhook", handle)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


# ================= MAIN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
