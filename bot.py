import os
import asyncio
import logging
import sqlite3

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update
from aiogram.enums import ParseMode

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")  # <-- В Render Secrets
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 10000))

# 🔥 2 OWNER ID
OWNERS = {123456789, 987654321}  # <-- ВСТАВЬ СЮДА СВОИ ID

# ================= BOT =================

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
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


# ================= TOURNAMENT CREATE =================

@dp.message(F.text.startswith("/create"))
async def create_tour(m: Message):
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


# ================= LIST =================

@dp.message(F.text.startswith("/list"))
async def list_tours(m: Message):
    rows = cursor.execute(
        "SELECT number, price FROM tournaments"
    ).fetchall()

    if not rows:
        return await m.answer("Нет турниров")

    text = "🏆 Список турниров:\n\n"
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

    await m.answer(f"💰 Цена: {price}\n💳 Карта: {card}")


# ================= PRICE =================

@dp.message(F.text.startswith("/price"))
async def price(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer("Формат: /price 1 100")

    number = int(parts[1])
    value = int(parts[2])

    cursor.execute(
        "UPDATE tournaments SET price=? WHERE number=?",
        (value, number)
    )
    conn.commit()

    await m.answer("💰 Цена обновлена")


# ================= CARD =================

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Формат: /card 1 текст")

    number = int(parts[1])
    value = parts[2]

    cursor.execute(
        "UPDATE tournaments SET card=? WHERE number=?",
        (value, number)
    )
    conn.commit()

    await m.answer("💳 Карта обновлена")


# ================= ROOM =================

@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        return await m.answer("Формат: /room 1 ссылка")

    number = int(parts[1])
    link = parts[2]

    cursor.execute(
        "UPDATE tournaments SET room=? WHERE number=?",
        (link, number)
    )
    conn.commit()

    await m.answer("🎮 Комната обновлена")


# ================= SEND (FIXED) =================

@dp.message(F.text.startswith("/send"))
async def send_all(m: Message):
    if not is_owner(m.from_user.id):
        return

    text = m.text.replace("/send", "").strip()
    if not text:
        return await m.answer("Формат: /send сообщение")

    users = cursor.execute("SELECT user_id FROM users").fetchall()

    count = 0
    for u in users:
        try:
            await bot.send_message(u[0], text)
            count += 1
        except:
            pass

    await m.answer(f"📢 Отправлено: {count}")


# ================= WEBHOOK HANDLER =================

async def webhook(request: web.Request):
    data = await request.json()

    # ❌ ВАЖНО: правильный способ (FIX ERROR)
    update = Update.model_validate(data)

    await dp.feed_update(bot, update)

    return web.Response(text="OK")


# ================= STARTUP =================

async def on_startup(app: web.Application):
    await bot.set_webhook(
        f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"
    )
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
