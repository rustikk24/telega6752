import os
import asyncio
import logging
import sqlite3

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties


# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_PATH = "/webhook"

OWNERS = {
    int(x) for x in os.getenv("OWNERS", "123456789,987654321").split(",")
}

WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # например https://your.onrender.com


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

def is_owner(user_id: int):
    return user_id in OWNERS


# ================= TOURNAMENT =================

@dp.message(F.text.startswith("/create"))
async def create(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("Формат: /create 1")

    number = int(parts[1])

    cursor.execute(
        "INSERT OR IGNORE INTO tournaments(number) VALUES (?)",
        (number,)
    )
    conn.commit()

    await m.answer("🏆 Турнир создан")


@dp.message(F.text.startswith("/list"))
async def list_tours(m: Message):
    rows = cursor.execute("SELECT number, price FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Нет турниров")

    text = "🏆 Турниры:\n\n"
    for r in rows:
        text += f"#{r[0]} — {r[1]}₽\n"

    await m.answer(text)


@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("Формат: /join 1")

    number = int(parts[1])

    tour = cursor.execute(
        "SELECT price, card FROM tournaments WHERE number=?",
        (number,)
    ).fetchone()

    if not tour:
        return await m.answer("Турнир не найден")

    price, card = tour

    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
        (m.from_user.id,)
    )
    conn.commit()

    await m.answer(f"💰 {price}\n💳 {card}")


# ================= ADMIN =================

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


@dp.message(F.text.startswith("/send"))
async def send_all(m: Message):
    if not is_owner(m.from_user.id):
        return

    text = m.text.replace("/send", "").strip()
    if not text:
        return await m.answer("Формат: /send текст")

    users = cursor.execute("SELECT user_id FROM users").fetchall()

    count = 0
    for u in users:
        try:
            await bot.send_message(u[0], text)
            count += 1
        except:
            pass

    await m.answer(f"📢 Отправлено: {count}")


# ================= WEBHOOK =================

async def webhook(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="OK")


# ================= STARTUP =================

async def on_startup(app: web.Application):
    await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logging.info("Webhook set")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()


# ================= APP =================

def main():
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
