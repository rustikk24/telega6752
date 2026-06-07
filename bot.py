import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= ENV =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
OWNERS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())

WEBHOOK_URL = BASE_URL + "/webhook"

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    card TEXT,
    room TEXT,
    start_time TEXT,
    max_players INTEGER DEFAULT 10
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    tour INTEGER,
    user_id INTEGER
)
""")

conn.commit()

# ================= STATES =================

class TourCreate(StatesGroup):
    num = State()
    price = State()
    time = State()
    maxp = State()

class RoomState(StatesGroup):
    data = State()

# ================= HELP =================

def is_owner(uid):
    return uid in OWNERS

# ================= KEYBOARDS =================

def main_menu(is_admin=False):
    kb = [
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="🧑‍💻 Админ", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Турнир", callback_data="create")],
        [InlineKeyboardButton(text="🏠 Рума", callback_data="room")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer("🎮 Меню", reply_markup=main_menu(is_owner(m.from_user.id)))

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cursor.execute(
        "SELECT number, price, start_time, room FROM tournaments"
    ).fetchall()

    text = "🎮 Турниры:\n\n"

    for n, p, t, r in rows:
        status = "🟢" if r else "🔴"
        text += f"#{n} | {p}₽ | {t} | {status}\n"

    await c.message.answer(text)

# ================= CREATE TOURNAMENT =================

@dp.callback_query(F.data == "create")
async def create(c: CallbackQuery, state: FSMContext):
    if not is_owner(c.from_user.id):
        return

    await c.message.answer("Номер турнира:")
    await state.set_state(TourCreate.num)

@dp.message(TourCreate.num)
async def num(m: Message, state: FSMContext):
    await state.update_data(num=m.text)
    await m.answer("Цена:")
    await state.set_state(TourCreate.price)

@dp.message(TourCreate.price)
async def price(m: Message, state: FSMContext):
    await state.update_data(price=m.text)
    await m.answer("Время (HH:MM):")
    await state.set_state(TourCreate.time)

@dp.message(TourCreate.time)
async def time(m: Message, state: FSMContext):
    await state.update_data(time=m.text)
    await m.answer("Макс игроков:")
    await state.set_state(TourCreate.maxp)

@dp.message(TourCreate.maxp)
async def maxp(m: Message, state: FSMContext):
    data = await state.get_data()

    cursor.execute("""
        INSERT OR REPLACE INTO tournaments
        (number, price, start_time, max_players)
        VALUES (?,?,?,?)
    """, (
        int(data["num"]),
        int(data["price"]),
        data["time"],
        int(m.text)
    ))

    conn.commit()
    await state.clear()

    await m.answer("✅ Турнир создан")

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery):
    await c.message.answer("Введите номер турнира:")

@dp.message()
async def join_handler(m: Message):
    if not m.text.isdigit():
        return

    num = int(m.text)

    tour = cursor.execute(
        "SELECT max_players FROM tournaments WHERE number=?",
        (num,)
    ).fetchone()

    if not tour:
        return

    count = cursor.execute(
        "SELECT COUNT(*) FROM players WHERE tour=?",
        (num,)
    ).fetchone()[0]

    if count >= tour[0]:
        return await m.answer("❌ Мест нет")

    cursor.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
    conn.commit()

    await m.answer("🎟 Ты записан!")

# ================= ROOM =================

@dp.callback_query(F.data == "room")
async def room(c: CallbackQuery, state: FSMContext):
    if not is_owner(c.from_user.id):
        return

    await c.message.answer("номер + рума")
    await state.set_state(RoomState.data)

@dp.message(RoomState.data)
async def save_room(m: Message, state: FSMContext):
    num, link = m.text.split(maxsplit=1)

    cursor.execute(
        "UPDATE tournaments SET room=? WHERE number=?",
        (link, int(num))
    )
    conn.commit()

    await state.clear()
    await m.answer("🏠 Рума сохранена")

# ================= TIMER SYSTEM =================

async def scheduler():
    while True:
        now = datetime.now()

        rows = cursor.execute(
            "SELECT number, room, start_time FROM tournaments"
        ).fetchall()

        for num, room, start_time in rows:
            if not room or not start_time:
                continue

            try:
                t = datetime.strptime(start_time, "%H:%M")
                target = now.replace(hour=t.hour, minute=t.minute, second=0)

                # 🔥 за 5 минут
                if now >= target - timedelta(minutes=5) and now < target - timedelta(minutes=4):

                    users = cursor.execute(
                        "SELECT user_id FROM players WHERE tour=?",
                        (num,)
                    ).fetchall()

                    for u in users:
                        try:
                            await bot.send_message(
                                u[0],
                                f"🏠 РУМА турнира #{num}:\n{room}"
                            )
                        except:
                            pass

                # 🚀 старт турнира
                if now >= target and now < target + timedelta(minutes=1):
                    users = cursor.execute(
                        "SELECT user_id FROM players WHERE tour=?",
                        (num,)
                    ).fetchall()

                    for u in users:
                        try:
                            await bot.send_message(
                                u[0],
                                f"🚀 ТУРНИР #{num} СТАРТОВАЛ!"
                            )
                        except:
                            pass

            except:
                pass

        await asyncio.sleep(30)

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    asyncio.create_task(scheduler())
    await bot.set_webhook(WEBHOOK_URL)
    print("WEBHOOK READY")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

# ================= APP =================

app = web.Application()
app.router.add_post("/webhook", handle)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# ================= RUN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
