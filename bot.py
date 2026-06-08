import asyncio
import time
import sqlite3
import os
from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
OWNERS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())

if not TOKEN:
    raise ValueError("BOT_TOKEN missing")
if not BASE_URL:
    raise ValueError("BASE_URL missing")

CHANNEL = "@ovqk_fun"
WEBHOOK_URL = BASE_URL + "/webhook"

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    max_players INTEGER,
    card TEXT,
    room TEXT,
    start_time INTEGER,
    room_sent INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS players (
    tour INTEGER,
    user_id INTEGER,
    paid INTEGER DEFAULT 0,
    receipt TEXT DEFAULT NULL
)
""")

conn.commit()


# ================= FSM =================

class JoinFSM(StatesGroup):
    tour = State()

class PayFSM(StatesGroup):
    tour = State()
    receipt = State()

class CreateFSM(StatesGroup):
    data = State()

class RoomFSM(StatesGroup):
    data = State()


# ================= SUB CHECK =================

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False


def sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url="https://t.me/ovqk_fun")],
        [InlineKeyboardButton(text="🔄 Проверить", callback_data="check_sub")]
    ])


# ================= MENU =================

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")],
        [InlineKeyboardButton(text="⚙ Админ", callback_data="admin")]
    ])


# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cur.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()

    if not await is_subscribed(m.from_user.id):
        return await m.answer("❌ Подпишись на канал", reply_markup=sub_keyboard())

    await m.answer("🎮 MENU", reply_markup=menu())


# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery, state: FSMContext):
    await state.set_state(JoinFSM.tour)
    await c.message.answer("Введите номер турнира")


@dp.message(JoinFSM.tour)
async def join_save(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return

    num = int(m.text)

    tour = cur.execute(
        "SELECT price, max_players, card FROM tournaments WHERE number=?",
        (num,)
    ).fetchone()

    if not tour:
        return await m.answer("❌ нет турнира")

    price, cap, card = tour

    exists = cur.execute(
        "SELECT 1 FROM players WHERE tour=? AND user_id=?",
        (num, m.from_user.id)
    ).fetchone()

    if exists:
        return await m.answer("❌ уже участвуешь")

    count = cur.execute(
        "SELECT COUNT(*) FROM players WHERE tour=?",
        (num,)
    ).fetchone()[0]

    if count >= cap:
        return await m.answer("❌ нет мест")

    cur.execute("INSERT INTO players VALUES (?,?,0,NULL)", (num, m.from_user.id))
    conn.commit()

    await state.set_state(PayFSM.receipt)
    await state.update_data(tour=num)

    await m.answer(f"💰 {price}₽\n💳 {card}\n📸 отправь чек")


# ================= RECEIPT =================

@dp.message(PayFSM.receipt)
async def receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    tour = data["tour"]

    file_id = None

    if m.photo:
        file_id = m.photo[-1].file_id
    elif m.document:
        file_id = m.document.file_id
    else:
        return await m.answer("❌ отправь фото или файл")

    cur.execute("""
        UPDATE players
        SET receipt=?, paid=0
        WHERE tour=? AND user_id=?
    """, (file_id, tour, m.from_user.id))

    conn.commit()

    for owner in OWNERS:
        await bot.send_message(owner, f"💰 Чек #{tour}\n/approve {tour} {m.from_user.id}")
        if m.photo:
            await bot.send_photo(owner, file_id)
        else:
            await bot.send_document(owner, file_id)

    await m.answer("⏳ на проверке")
    await state.clear()


# ================= APPROVE =================

@dp.message(F.text.startswith("/approve"))
async def approve(m: Message):
    if m.from_user.id not in OWNERS:
        return

    try:
        _, tour, user_id = m.text.split()
        tour = int(tour)
        user_id = int(user_id)

        cur.execute("""
            UPDATE players
            SET paid=1
            WHERE tour=? AND user_id=?
        """, (tour, user_id))

        conn.commit()

        await bot.send_message(user_id, f"✅ Оплата подтверждена #{tour}")
        await m.answer("✅ ok")

    except:
        await m.answer("❌ /approve tour user_id")


# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")


async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    print("BOT STARTED")


app = web.Application()
app.router.add_post("/webhook", handle)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
