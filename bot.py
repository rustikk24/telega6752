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
    max_players INTEGER,
    room TEXT DEFAULT ''
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    tour INTEGER,
    user_id INTEGER,
    UNIQUE(tour, user_id)
)
""")

conn.commit()

# ================= FSM =================

class CreateTournament(StatesGroup):
    number = State()
    price = State()
    max_players = State()

class JoinTournament(StatesGroup):
    tour = State()

class RoomFSM(StatesGroup):
    data = State()

# ================= HELP =================

def is_owner(uid: int):
    return uid in OWNERS

# ================= MENU =================

def menu(admin=False):
    kb = [
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="list")],
        [InlineKeyboardButton(text="🎟 Участвовать", callback_data="join")],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data="leave")]
    ]
    if admin:
        kb.append([InlineKeyboardButton(text="⚙ Админ", callback_data="admin")])

    return InlineKeyboardMarkup(inline_keyboard=kb)

admin_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Создать турнир", callback_data="create")],
    [InlineKeyboardButton(text="📋 Турниры", callback_data="admin_list")],
    [InlineKeyboardButton(text="👥 Игроки", callback_data="admin_players")],
    [InlineKeyboardButton(text="🏠 Румы", callback_data="admin_room")],
    [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete")]
])

# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    await m.answer("🎮 Главное меню", reply_markup=menu(is_owner(m.from_user.id)))

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cursor.execute("SELECT number, price, max_players, room FROM tournaments").fetchall()

    if not rows:
        return await c.message.answer("Нет турниров")

    text = "🎮 Турниры:\n\n"
    for n, p, mpx, r in rows:
        count = cursor.execute("SELECT COUNT(*) FROM players WHERE tour=?", (n,)).fetchone()[0]
        text += f"#{n} | {p}₽ | {count}/{mpx} | {'🟢' if r else '🔴'}\n"

    await c.message.answer(text)

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Введи номер турнира")
    await state.set_state(JoinTournament.tour)

@dp.message(JoinTournament.tour)
async def join_handler(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Нужно число")

    num = int(m.text)

    tour = cursor.execute("SELECT max_players FROM tournaments WHERE number=?", (num,)).fetchone()
    if not tour:
        return await m.answer("❌ Турнир не найден")

    exists = cursor.execute(
        "SELECT 1 FROM players WHERE tour=? AND user_id=?",
        (num, m.from_user.id)
    ).fetchone()

    if exists:
        return await m.answer("⚠️ Ты уже в турнире")

    count = cursor.execute("SELECT COUNT(*) FROM players WHERE tour=?", (num,)).fetchone()[0]

    if count >= tour[0]:
        return await m.answer("❌ Мест нет")

    cursor.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
    conn.commit()

    await state.clear()
    await m.answer("🎟 Ты записан")

# ================= LEAVE =================

@dp.callback_query(F.data == "leave")
async def leave(c: CallbackQuery):
    cursor.execute("DELETE FROM players WHERE user_id=?", (c.from_user.id,))
    conn.commit()
    await c.message.answer("🚪 Ты вышел из всех турниров")

# ================= ADMIN =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if not is_owner(c.from_user.id):
        return await c.answer("⛔ нет доступа", show_alert=True)

    await c.message.answer("⚙ ADMIN PANEL", reply_markup=admin_kb)

# ================= CREATE TOURNAMENT =================

@dp.callback_query(F.data == "create")
async def create(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Введите номер турнира")
    await state.set_state(CreateTournament.number)

@dp.message(CreateTournament.number)
async def create_num(m: Message, state: FSMContext):
    await state.update_data(number=int(m.text))
    await m.answer("Цена (₽)")
    await state.set_state(CreateTournament.price)

@dp.message(CreateTournament.price)
async def create_price(m: Message, state: FSMContext):
    await state.update_data(price=int(m.text))
    await m.answer("Макс игроков")
    await state.set_state(CreateTournament.max_players)

@dp.message(CreateTournament.max_players)
async def create_finish(m: Message, state: FSMContext):
    data = await state.get_data()

    cursor.execute("""
        INSERT INTO tournaments(number, price, max_players)
        VALUES (?,?,?)
    """, (data["number"], data["price"], int(m.text)))

    conn.commit()
    await state.clear()

    await m.answer("✅ Турнир создан")

# ================= ADMIN LIST =================

@dp.callback_query(F.data == "admin_list")
async def admin_list(c: CallbackQuery):
    rows = cursor.execute("SELECT * FROM tournaments").fetchall()

    text = "📋 Турниры:\n\n"
    for n, p, mpx, r in rows:
        text += f"#{n} | {p}₽ | {mpx} слотов | {'🟢' if r else '🔴'}\n"

    await c.message.answer(text)

# ================= PLAYERS =================

@dp.callback_query(F.data == "admin_players")
async def players(c: CallbackQuery):
    rows = cursor.execute("SELECT tour, user_id FROM players").fetchall()

    text = "👥 Игроки:\n\n"
    for t, u in rows:
        text += f"#{t} → {u}\n"

    await c.message.answer(text)

# ================= DELETE =================

@dp.callback_query(F.data == "admin_delete")
async def delete_prompt(c: CallbackQuery):
    await c.message.answer("Введи номер турнира")

@dp.message(F.text.regexp(r"^\d+$"))
async def delete(m: Message):
    if not is_owner(m.from_user.id):
        return

    num = int(m.text)

    cursor.execute("DELETE FROM tournaments WHERE number=?", (num,))
    cursor.execute("DELETE FROM players WHERE tour=?", (num,))
    conn.commit()

    await m.answer("🗑 Удалено")

# ================= ROOM =================

@dp.callback_query(F.data == "admin_room")
async def room(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Введи: номер + ссылка")
    await state.set_state(RoomFSM.data)

@dp.message(RoomFSM.data)
async def set_room(m: Message, state: FSMContext):
    num, link = m.text.split(maxsplit=1)

    cursor.execute("UPDATE tournaments SET room=? WHERE number=?", (link, int(num)))
    conn.commit()

    await state.clear()
    await m.answer("🏠 Рума обновлена")

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    print("WEBHOOK OK")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

# ================= RUN =================

app = web.Application()
app.router.add_post("/webhook", handle)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
