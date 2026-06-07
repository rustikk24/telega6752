import asyncio
import logging
import os
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

class RoomFSM(StatesGroup):
    data = State()

# ================= HELP =================

def is_owner(uid: int):
    return uid in OWNERS

# ================= MENU =================

def menu(admin=False):
    kb = [
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")]
    ]
    if admin:
        kb.append([InlineKeyboardButton(text="⚙ Админ", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=kb)

admin_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Создать", callback_data="create")],
    [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
    [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_players")],
    [InlineKeyboardButton(text="🏠 Рума", callback_data="admin_room")],
    [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete")]
])

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer("🎮 Меню", reply_markup=menu(is_owner(m.from_user.id)))

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cursor.execute("SELECT number, price, room FROM tournaments").fetchall()

    text = "🎮 Турниры:\n\n"
    for n, p, r in rows:
        status = "🟢" if r else "🔴"
        text += f"#{n} | {p}₽ | {status}\n"

    await c.message.answer(text)

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery):
    await c.message.answer("Напиши номер турнира")

@dp.message()
async def join_handler(m: Message):
    if not m.text.isdigit():
        return

    num = int(m.text)

    cap = cursor.execute("SELECT max_players FROM tournaments WHERE number=?", (num,)).fetchone()
    if not cap:
        return

    count = cursor.execute("SELECT COUNT(*) FROM players WHERE tour=?", (num,)).fetchone()[0]

    if count >= cap[0]:
        return await m.answer("❌ Мест нет")

    cursor.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
    conn.commit()

    await m.answer("🎟 Участвовал")

# ================= ADMIN =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if not is_owner(c.from_user.id):
        return await c.answer("⛔ нет доступа", show_alert=True)

    await c.message.answer("⚙ ADMIN PANEL", reply_markup=admin_kb)

# ================= CREATE =================

@dp.callback_query(F.data == "create")
async def create(c: CallbackQuery):
    await c.message.answer("Создание пока вручную через БД / можно расширить FSM")

# ================= LIST ADMIN =================

@dp.callback_query(F.data == "admin_list")
async def admin_list(c: CallbackQuery):
    rows = cursor.execute("SELECT number, price, room, max_players FROM tournaments").fetchall()

    text = "📋 TOURNAMENTS:\n\n"
    for n, p, r, m in rows:
        text += f"#{n} | {p}₽ | {m} слотов | {'🟢' if r else '🔴'}\n"

    await c.message.answer(text)

# ================= PLAYERS =================

@dp.callback_query(F.data == "admin_players")
async def players(c: CallbackQuery):
    rows = cursor.execute("SELECT tour, user_id FROM players").fetchall()

    text = "👥 PLAYERS:\n\n"
    for t, u in rows:
        text += f"{t} → {u}\n"

    await c.message.answer(text)

# ================= ROOM =================

@dp.callback_query(F.data == "admin_room")
async def room(c: CallbackQuery, state: FSMContext):
    await c.message.answer("номер + ссылка")
    await state.set_state(RoomFSM.data)

@dp.message(RoomFSM.data)
async def set_room(m: Message, state: FSMContext):
    num, link = m.text.split(maxsplit=1)

    cursor.execute("UPDATE tournaments SET room=? WHERE number=?", (link, int(num)))
    conn.commit()

    await state.clear()
    await m.answer("🏠 Рума сохранена")

# ================= DELETE =================

@dp.callback_query(F.data == "admin_delete")
async def del_hint(c: CallbackQuery):
    await c.message.answer("Напиши номер турнира")

@dp.message(F.text.regexp(r"^\d+$"))
async def delete(m: Message):
    if not is_owner(m.from_user.id):
        return

    num = int(m.text)

    cursor.execute("DELETE FROM tournaments WHERE number=?", (num,))
    cursor.execute("DELETE FROM players WHERE tour=?", (num,))
    conn.commit()

    await m.answer("🗑 удалено")

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    print("WEBHOOK READY:", WEBHOOK_URL)

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
