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
    max_players INTEGER
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

class AddTour(StatesGroup):
    data = State()

class BanUser(StatesGroup):
    uid = State()

class JoinTour(StatesGroup):
    tour = State()

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
        [InlineKeyboardButton(text="⚙ Админ панель", callback_data="admin")]
    ])

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    if await is_banned(m.from_user.id):
        return await m.answer("⛔ banned")

    await m.answer("🎮 MENU", reply_markup=menu())

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery, state: FSMContext):
    await state.set_state(JoinTour.tour)
    await c.message.answer("Введи номер турнира")

@dp.message(JoinTour.tour)
async def join_save(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ число")

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

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cur.execute("SELECT number, price, max_players FROM tournaments").fetchall()

    text = "🎮 TOURNAMENTS\n\n"
    for n, p, m in rows:
        text += f"#{n} | {p}₽ | {m} slots\n"

    await c.message.answer(text)

# ================= ADMIN PANEL =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if c.from_user.id not in OWNERS:
        return await c.answer("⛔ no access", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать турнир", callback_data="add")],
        [InlineKeyboardButton(text="🗑 Удалить турнир", callback_data="del")],
        [InlineKeyboardButton(text="📋 Турниры", callback_data="adm_list")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="adm_players")],
        [InlineKeyboardButton(text="🚫 Бан", callback_data="ban")]
    ])

    await c.message.answer("⚙ <b>ADMIN PANEL</b>", reply_markup=kb)

# ================= ADD TOURNAMENT =================

@dp.callback_query(F.data == "add")
async def add(c: CallbackQuery, state: FSMContext):
    if c.from_user.id not in OWNERS:
        return
    await state.set_state(AddTour.data)
    await c.message.answer("Введи: номер цена слоты")

@dp.message(AddTour.data)
async def add_save(m: Message, state: FSMContext):
    try:
        n, p, s = map(int, m.text.split())

        cur.execute("INSERT OR REPLACE INTO tournaments VALUES (?,?,?)", (n, p, s))
        conn.commit()

        await m.answer("✅ создано")
    except:
        await m.answer("❌ формат: номер цена слоты")

    await state.clear()

# ================= DELETE =================

@dp.callback_query(F.data == "del")
async def del_hint(c: CallbackQuery, state: FSMContext):
    await state.set_state(AddTour.data)
    await c.message.answer("Введи номер турнира")

@dp.message(AddTour.data)
async def del_run(m: Message, state: FSMContext):
    if m.from_user.id not in OWNERS:
        return

    if m.text.isdigit():
        n = int(m.text)

        cur.execute("DELETE FROM tournaments WHERE number=?", (n,))
        cur.execute("DELETE FROM players WHERE tour=?", (n,))
        conn.commit()

        await m.answer("🗑 удалено")

    await state.clear()

# ================= ADM LIST =================

@dp.callback_query(F.data == "adm_list")
async def adm_list(c: CallbackQuery):
    rows = cur.execute("SELECT number, price, max_players FROM tournaments").fetchall()

    text = "📋 TOURNAMENTS\n\n"
    for r in rows:
        text += f"#{r[0]} | {r[1]}₽ | {r[2]} slots\n"

    await c.message.answer(text)

# ================= PLAYERS =================

@dp.callback_query(F.data == "adm_players")
async def adm_players(c: CallbackQuery):
    rows = cur.execute("SELECT tour, user_id FROM players").fetchall()

    text = "👥 PLAYERS\n\n"
    for t, u in rows:
        text += f"{t} → {u}\n"

    await c.message.answer(text)

# ================= BAN =================

@dp.callback_query(F.data == "ban")
async def ban_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(BanUser.uid)
    await c.message.answer("ID для бана")

@dp.message(BanUser.uid)
async def ban_save(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("ID число")

    uid = int(m.text)

    cur.execute("INSERT OR IGNORE INTO bans VALUES (?)", (uid,))
    conn.commit()

    await state.clear()
    await m.answer("🚫 banned")

# ================= DEBUG =================

@dp.message(F.text == "/debug")
async def debug(m: Message):
    info = await bot.get_webhook_info()
    uptime = int(time.time() - START_TIME)

    await m.answer(
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
        print("ERR:", e)

    return web.Response(text="ok")

async def index(request):
    return web.Response(text="BOT OK")

async def on_startup(app):
    print("BOT STARTED")
    await bot.set_webhook(WEBHOOK_URL)

app = web.Application()
app.router.add_post("/webhook", handle)
app.router.add_get("/", index)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
