import asyncio
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
from aiogram.exceptions import TelegramForbiddenError


# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")

OWNER_IDS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())
FALLBACK_ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")

cur.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
    number INTEGER PRIMARY KEY,
    price INTEGER,
    max_players INTEGER,
    card TEXT,
    bank TEXT,
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
    receipt TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bans (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()


# ================= SAFE DB =================

def db_fetch(q, a=()):
    cur.execute(q, a)
    return cur.fetchone()

def db_fetchall(q, a=()):
    cur.execute(q, a)
    return cur.fetchall()

def db_exec(q, a=()):
    cur.execute(q, a)
    conn.commit()


# ================= ADMIN =================

def is_admin(uid: int):
    return uid in OWNER_IDS or uid == FALLBACK_ADMIN_ID


# ================= SAFE SEND (FIX CRASH) =================

async def safe_send(msg: Message, text: str, **kwargs):
    try:
        return await msg.answer(text, **kwargs)
    except TelegramForbiddenError:
        print(f"[BLOCKED USER] {msg.from_user.id}")
        return
    except Exception as e:
        print("SEND ERROR:", e)


# ================= BAN =================

def is_banned(uid: int):
    r = db_fetch("SELECT 1 FROM bans WHERE user_id=?", (uid,))
    return r is not None


# ================= MENU =================

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="👤 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="⚙ Админ", callback_data="admin")]
    ])


# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):

    if is_banned(m.from_user.id):
        return

    db_exec("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))

    await safe_send(m, "🎮 MENU", reply_markup=menu())


# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_tournaments(c: CallbackQuery):

    rows = db_fetchall(
        "SELECT number, price, max_players, room_sent FROM tournaments"
    )

    if not rows:
        return await c.message.answer("❌ турниров нет")

    text = "🎮 Турниры:\n\n"

    for n, p, cap, room in rows:
        status = "🏁 есть рума" if room else "🔴 нет рума"
        text += f"#{n} | {p}₽ | {cap} мест | {status}\n"

    await c.message.answer(text)


# ================= STATS =================

@dp.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):

    rows = db_fetchall(
        "SELECT tour FROM players WHERE user_id=?",
        (c.from_user.id,)
    )

    if not rows:
        return await c.message.answer("📊 нет данных")

    text = "📊 СТАТИСТИКА:\n\n"

    for r in rows:
        text += f"🎮 Турнир #{r[0]}\n"

    await c.message.answer(text)


# ================= ADMIN =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):

    if not is_admin(c.from_user.id):
        return await c.answer("⛔ нет доступа", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🎮 турниры", callback_data="adm_tour")],
        [InlineKeyboardButton("👥 игроки", callback_data="adm_players")],
        [InlineKeyboardButton("🔨 бан", callback_data="adm_ban")]
    ])

    await c.message.answer("⚙ ADMIN PANEL", reply_markup=kb)


# ================= ADMIN TOURS =================

@dp.callback_query(F.data == "adm_tour")
async def adm_tour(c: CallbackQuery):

    rows = db_fetchall("SELECT number, price, bank FROM tournaments")

    text = "🎮 ТУРНИРЫ:\n\n"

    for n, p, b in rows:
        text += f"#{n} | {p}₽ | 💳 {b}\n"

    await c.message.answer(text)


# ================= ADMIN PLAYERS =================

@dp.callback_query(F.data == "adm_players")
async def adm_players(c: CallbackQuery):

    rows = db_fetchall("SELECT user_id, tour FROM players")

    text = "👥 ИГРОКИ:\n\n"

    for u, t in rows:
        text += f"👤 {u} → #{t}\n"

    await c.message.answer(text)


# ================= BAN SYSTEM =================

@dp.callback_query(F.data == "adm_ban")
async def ban_menu(c: CallbackQuery):

    if not is_admin(c.from_user.id):
        return

    await c.message.answer("✍ отправь user_id для бана")


@dp.message(F.text)
async def ban_user(m: Message):

    if not is_admin(m.from_user.id):
        return

    if m.text.isdigit():
        uid = int(m.text)

        db_exec("INSERT OR IGNORE INTO bans VALUES (?)", (uid,))

        await safe_send(m, f"⛔ забанен {uid}")


# ================= WEBHOOK (ANTI CRASH) =================

async def handle(request):
    try:
        data = await request.json()
        update = types.Update.model_validate(data)
        await dp.feed_update(bot, update)
    except Exception as e:
        print("WEBHOOK ERROR:", e)

    return web.Response(text="ok")


async def on_startup(app):
    await bot.set_webhook(BASE_URL + "/webhook")
    print("BOT STARTED")


app = web.Application()
app.router.add_post("/webhook", handle)
app.on_startup.append(on_startup)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
