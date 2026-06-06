import asyncio
import logging
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

# ================= CONFIG =================

TOKEN = "PUT_YOUR_TOKEN_HERE"

OWNERS = {
    6279994177,
    5857555465
}

# ================= BOT INIT =================

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

def is_owner(user_id: int) -> bool:
    return user_id in OWNERS

def add_user(user_id: int):
    cursor.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    add_user(m.from_user.id)
    await m.answer("👋 Привет! Бот турниров активирован")

# ================= CREATE TOURNAMENT =================

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

    await m.answer(f"✅ Турнир {number} создан")

# ================= LIST =================

@dp.message(F.text == "/list")
async def list_tours(m: Message):
    if not is_owner(m.from_user.id):
        return

    tours = cursor.execute(
        "SELECT number, price, card, room FROM tournaments"
    ).fetchall()

    if not tours:
        return await m.answer("❌ Турниров нет")

    text = "📋 Турниры:\n\n"

    for t in tours:
        text += (
            f"🎮 {t[0]}\n"
            f"💰 {t[1]}\n"
            f"💳 {t[2]}\n"
            f"🎮 {t[3]}\n\n"
        )

    await m.answer(text)

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

# ================= SEND =================

@dp.message(F.text.startswith("/send"))
async def send_all(m: Message):
    if not is_owner(m.from_user.id):
        return

    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Формат: /send текст")

    text = parts[1]

    users = cursor.execute("SELECT user_id FROM users").fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], text)
        except:
            pass

    await m.answer("📢 Рассылка отправлена")

# ================= FALLBACK =================

@dp.message()
async def fallback(m: Message):
    await m.answer("❓ Неизвестная команда")

# ================= MAIN =================

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
