import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ================= ENV =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
OWNERS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())

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
    price INTEGER,
    max_players INTEGER,
    bank TEXT,
    card TEXT,
    room TEXT,
    start_time TEXT,
    room_sent INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS registrations (
    user_id INTEGER,
    tournament_id INTEGER,
    paid INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, tournament_id)
)
""")

conn.commit()

# ================= HELP =================

def is_owner(uid: int):
    return uid in OWNERS

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()
    await m.answer("🤖 Бот турниров активен")

# ================= TOUR =================

@dp.message(F.text.startswith("/tour"))
async def tour(m: Message):
    if not is_owner(m.from_user.id):
        return

    _, num, price, limit, date, time = m.text.split()

    start_time = f"{date} {time}"

    cursor.execute("""
    INSERT OR REPLACE INTO tournaments
    (number, price, max_players, start_time)
    VALUES (?, ?, ?, ?)
    """, (int(num), int(price), int(limit), start_time))

    conn.commit()
    await m.answer("🎮 Турнир создан")

# ================= LIST =================

@dp.message(F.text == "/list")
async def list_t(m: Message):
    rows = cursor.execute("SELECT number, price, max_players, room FROM tournaments").fetchall()

    if not rows:
        return await m.answer("Нет турниров")

    text = "🎮 Турниры\n\n"

    for num, price, maxp, room in rows:

        cnt = cursor.execute(
            "SELECT COUNT(*) FROM registrations WHERE tournament_id=?",
            (num,)
        ).fetchone()[0]

        room_status = "🟢" if room else "🔴"

        text += (
            f"#{num}\n"
            f"💰 {price}₽\n"
            f"👥 {cnt}/{maxp}\n"
            f"🏠 Рума: {room_status}\n\n"
        )

    await m.answer(text)

# ================= JOIN =================

@dp.message(F.text.startswith("/join"))
async def join(m: Message):
    _, num = m.text.split()
    num = int(num)

    t = cursor.execute(
        "SELECT price, max_players FROM tournaments WHERE number=?",
        (num,)
    ).fetchone()

    if not t:
        return await m.answer("Турнир не найден")

    price, maxp = t

    cnt = cursor.execute(
        "SELECT COUNT(*) FROM registrations WHERE tournament_id=?",
        (num,)
    ).fetchone()[0]

    if cnt >= maxp:
        return await m.answer("❌ Лимит игроков")

    cursor.execute(
        "INSERT OR IGNORE INTO registrations VALUES (?, ?, 0)",
        (m.from_user.id, num)
    )

    conn.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📸 Отправить чек", callback_data=f"pay_{num}")
    ]])

    await m.answer(
        f"🎮 Турнир #{num}\n💰 {price}₽\n\nОтправьте чек оплаты",
        reply_markup=kb
    )

# ================= PAYMENT BUTTON =================

@dp.callback_query(F.data.startswith("pay_"))
async def pay(call: CallbackQuery):
    num = int(call.data.split("_")[1])

    owners_list = "\n".join(str(x) for x in OWNERS)

    await bot.send_message(
        list(OWNERS)[0],
        f"💳 Чек\nUser: {call.from_user.id}\nTournament: {num}"
    )

    await call.message.answer("📤 Чек отправлен администратору")

# ================= CARD =================

@dp.message(F.text.startswith("/card"))
async def card(m: Message):
    if not is_owner(m.from_user.id):
        return

    _, num, bank, card = m.text.split(maxsplit=3)

    cursor.execute("""
    UPDATE tournaments
    SET bank=?, card=?
    WHERE number=?
    """, (bank, card, int(num)))

    conn.commit()

    await m.answer("💳 Карта обновлена")

# ================= ROOM =================

@dp.message(F.text.startswith("/room"))
async def room(m: Message):
    if not is_owner(m.from_user.id):
        return

    _, num, link = m.text.split(maxsplit=2)

    cursor.execute("""
    UPDATE tournaments
    SET room=?
    WHERE number=?
    """, (link, int(num)))

    conn.commit()

    await m.answer("🏠 Рума задана")

# ================= DELETE =================

@dp.message(F.text.startswith("/delete"))
async def delete(m: Message):
    if not is_owner(m.from_user.id):
        return

    _, num = m.text.split()

    cursor.execute("DELETE FROM tournaments WHERE number=?", (int(num),))
    cursor.execute("DELETE FROM registrations WHERE tournament_id=?", (int(num),))
    conn.commit()

    await m.answer("🗑 Удалено")

# ================= SEND =================

@dp.message(F.text.startswith("/send"))
async def send(m: Message):
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

# ================= AUTO ROOM =================

async def room_sender():
    while True:
        now = datetime.now()

        rows = cursor.execute("SELECT number, start_time, room, room_sent FROM tournaments").fetchall()

        for num, start_time, room, sent in rows:
            if not room or sent:
                continue

            try:
                dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            except:
                continue

            if now >= dt - timedelta(minutes=5):

                users = cursor.execute(
                    "SELECT user_id FROM registrations WHERE tournament_id=?",
                    (num,)
                ).fetchall()

                for u in users:
                    try:
                        await bot.send_message(u[0], f"🚨 Рума:\n{room}")
                    except:
                        pass

                cursor.execute(
                    "UPDATE tournaments SET room_sent=1 WHERE number=?",
                    (num,)
                )
                conn.commit()

        await asyncio.sleep(30)

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(room_sender())
    print("Webhook set")

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
