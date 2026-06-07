import asyncio
import logging
import os
import time
import sqlite3

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

WEBHOOK_URL = (BASE_URL or "") + "/webhook"
START_TIME = time.time()

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    max_players INTEGER DEFAULT 10
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS players (
    tour INTEGER,
    user_id INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bans (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()

# ================= FSM =================

class JoinFSM(StatesGroup):
    tour = State()

class BanFSM(StatesGroup):
    user = State()

# ================= HELPERS =================

def is_owner(uid: int):
    return uid in OWNERS

async def is_banned(uid: int):
    c = conn.cursor()
    c.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,))
    return c.fetchone() is not None

# ================= MENU =================

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")],
        [InlineKeyboardButton(text="🛡 Модерация", callback_data="mod")],
        [InlineKeyboardButton(text="🧠 Debug", callback_data="debug")]
    ])

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    if await is_banned(m.from_user.id):
        return await m.answer("⛔ banned")

    await m.answer("🎮 MENU", reply_markup=menu())

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cur.execute("SELECT number, price FROM tournaments").fetchall()

    text = "🎮 TOURNAMENTS\n\n"
    for n, p in rows:
        text += f"#{n} | {p}₽\n"

    await c.message.answer(text)

# ================= JOIN (FSM) =================

@dp.callback_query(F.data == "join")
async def join_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(JoinFSM.tour)
    await c.message.answer("Введи номер турнира")

@dp.message(JoinFSM.tour)
async def join_finish(m: Message, state: FSMContext):
    if await is_banned(m.from_user.id):
        return

    if not m.text.isdigit():
        return await m.answer("Введите число")

    num = int(m.text)

    cap = cur.execute("SELECT max_players FROM tournaments WHERE number=?", (num,)).fetchone()
    if not cap:
        await state.clear()
        return await m.answer("❌ нет турнира")

    count = cur.execute("SELECT COUNT(*) FROM players WHERE tour=?", (num,)).fetchone()[0]

    if count >= cap[0]:
        await state.clear()
        return await m.answer("❌ full")

    cur.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
    conn.commit()

    await state.clear()
    await m.answer("✅ joined")

# ================= MOD =================

@dp.callback_query(F.data == "mod")
async def mod(c: CallbackQuery):
    if not is_owner(c.from_user.id):
        return await c.answer("⛔", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Ban", callback_data="ban")]
    ])

    await c.message.answer("🛡 MOD", reply_markup=kb)

# ================= BAN (FSM FIX) =================

@dp.callback_query(F.data == "ban")
async def ban_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(BanFSM.user)
    await c.message.answer("Введи ID пользователя")

@dp.message(BanFSM.user)
async def ban_finish(m: Message, state: FSMContext):
    if not is_owner(m.from_user.id):
        return

    if not m.text.isdigit():
        return await m.answer("ID должен быть числом")

    uid = int(m.text)

    cur.execute("INSERT OR IGNORE INTO bans VALUES (?)", (uid,))
    conn.commit()

    await state.clear()
    await m.answer("🚫 banned")

# ================= DEBUG =================

@dp.callback_query(F.data == "debug")
async def debug(c: CallbackQuery):
    info = await bot.get_webhook_info()
    uptime = int(time.time() - START_TIME)

    await c.message.answer(
        f"🧠 DEBUG\n"
        f"Webhook: {info.url}\n"
        f"Pending: {info.pending_update_count}\n"
        f"Uptime: {uptime}s"
    )

# ================= WEBHOOK =================

async def handle(request):
    try:
        data = await request.json()
        update = types.Update.model_validate(data)
        await dp.feed_update(bot, update)
    except Exception as e:
        print("WEBHOOK ERROR:", e)

    return web.Response(text="ok")

async def index(request):
    return web.Response(text="BOT OK")

# ================= STARTUP =================

async def on_startup(app):
    print("BOT STARTED")

    await bot.set_webhook(WEBHOOK_URL)

    print("WEBHOOK SET:", WEBHOOK_URL)

# ================= APP =================

app = web.Application()
app.router.add_post("/webhook", handle)
app.router.add_get("/", index)
app.on_startup.append(on_startup)

# ================= RUN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
