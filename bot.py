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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= CONFIG =================

DEBUG_MODE = True
START_TIME = time.time()

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
OWNERS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())

WEBHOOK_URL = (BASE_URL or "") + "/webhook"

# ================= BOT =================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# ================= LOG =================

def log(msg):
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}")

# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    max_players INTEGER DEFAULT 10,
    room TEXT DEFAULT ''
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

class RoomFSM(StatesGroup):
    data = State()

# ================= HELPERS =================

def is_owner(uid: int):
    return uid in OWNERS

# ================= KEYBOARD =================

def menu(admin=False):
    kb = [
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")],
        [InlineKeyboardButton(text="🛡 Модерация", callback_data="mod")],
        [InlineKeyboardButton(text="🧠 Debug", callback_data="debug_btn")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    log(f"START {m.from_user.id}")

    if await is_banned(m.from_user.id):
        return await m.answer("⛔ banned")

    await m.answer("🎮 MENU", reply_markup=menu(is_owner(m.from_user.id)))

# ================= BAN CHECK =================

async def is_banned(uid: int):
    c = conn.cursor()
    c.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,))
    return c.fetchone() is not None

# ================= TOURNAMENT LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cur.execute("SELECT number, price, room FROM tournaments").fetchall()

    text = "🎮 TOURNAMENTS\n\n"
    for n, p, r in rows:
        text += f"#{n} | {p}₽ | {'🟢' if r else '🔴'}\n"

    await c.message.answer(text)

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery):
    await c.message.answer("Введи номер турнира")

@dp.message(F.text.regexp(r"^\d+$"))
async def join_handler(m: Message):
    if await is_banned(m.from_user.id):
        return

    num = int(m.text)

    cap = cur.execute("SELECT max_players FROM tournaments WHERE number=?", (num,)).fetchone()
    if not cap:
        return

    count = cur.execute("SELECT COUNT(*) FROM players WHERE tour=?", (num,)).fetchone()[0]

    if count >= cap[0]:
        return await m.answer("❌ full")

    cur.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
    conn.commit()

    await m.answer("✅ joined")

# ================= MODERATION =================

@dp.callback_query(F.data == "mod")
async def mod_menu(c: CallbackQuery):
    if not is_owner(c.from_user.id):
        return await c.answer("⛔", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Ban", callback_data="ban")],
        [InlineKeyboardButton(text="✅ Unban", callback_data="unban")]
    ])

    await c.message.answer("🛡 MOD", reply_markup=kb)

# ================= BAN =================

@dp.callback_query(F.data == "ban")
async def ban_hint(c: CallbackQuery):
    await c.message.answer("send user id")

@dp.message(F.text.regexp(r"^\d+$"))
async def ban_user(m: Message):
    if not is_owner(m.from_user.id):
        return

    uid = int(m.text)

    cur.execute("INSERT OR IGNORE INTO bans VALUES (?)", (uid,))
    conn.commit()

    await m.answer("🚫 banned")

# ================= DEBUG PANEL =================

@dp.message(F.text == "/debug")
async def debug_cmd(m: Message):
    if m.from_user.id not in OWNERS:
        return

    info = await bot.get_webhook_info()
    uptime = int(time.time() - START_TIME)

    await m.answer(
        "🧠 DEBUG\n\n"
        f"Webhook: {info.url}\n"
        f"Pending: {info.pending_update_count}\n"
        f"Uptime: {uptime}s\n"
    )

# ================= CALLBACK DEBUG =================

@dp.callback_query(F.data == "debug_btn")
async def debug_btn(c: CallbackQuery):
    info = await bot.get_webhook_info()
    uptime = int(time.time() - START_TIME)

    await c.message.answer(
        f"🧠 DEBUG\nWebhook: {info.url}\nPending: {info.pending_update_count}\nUptime: {uptime}s"
    )

# ================= WEBHOOK WATCHER =================

async def webhook_watcher():
    while True:
        try:
            info = await bot.get_webhook_info()

            if info.url != WEBHOOK_URL:
                await bot.set_webhook(WEBHOOK_URL)
                log("webhook fixed")

        except Exception as e:
            log(f"webhook error: {e}")

        await asyncio.sleep(30)

# ================= WEB SERVER =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def index(request):
    return web.Response(text="BOT OK (DEBUG MODE)")

# ================= STARTUP =================

async def on_startup(app):
    log("START")

    await bot.set_webhook(WEBHOOK_URL)

    asyncio.create_task(webhook_watcher())

    log("READY")

# ================= APP =================

app = web.Application()
app.router.add_post("/webhook", handle)
app.router.add_get("/", index)
app.on_startup.append(on_startup)

# ================= RUN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
