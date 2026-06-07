import asyncio
import time
import sqlite3
import os

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

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

START_TIME = time.time()

# ================= DB =================

conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

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
    paid INTEGER DEFAULT 0
)
""")

conn.commit()

# ================= FSM =================

class JoinFSM(StatesGroup):
    tour = State()

class CreateFSM(StatesGroup):
    data = State()

class RoomFSM(StatesGroup):
    data = State()

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

    await m.answer("🎮 MENU", reply_markup=menu())

# ================= LIST =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    rows = cur.execute("""
        SELECT number, price, max_players, room_sent
        FROM tournaments
    """).fetchall()

    text = "🎮 TOURNAMENTS\n\n"

    for n, p, cap, sent in rows:
        status = "🏁 RUМА ЕСТЬ" if sent else "🔴 RUМЫ НЕТ"
        text += f"#{n} | {p}₽ | {cap} slots | {status}\n"

    await c.message.answer(text)

# ================= JOIN =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery, state: FSMContext):
    await state.set_state(JoinFSM.tour)
    await c.message.answer("Введите номер турнира")

@dp.message(JoinFSM.tour)
async def join_save(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ число")

    num = int(m.text)

    tour = cur.execute("""
        SELECT price, max_players, card
        FROM tournaments WHERE number=?
    """, (num,)).fetchone()

    if not tour:
        await state.clear()
        return await m.answer("❌ нет турнира")

    price, cap, card = tour

    count = cur.execute(
        "SELECT COUNT(*) FROM players WHERE tour=?",
        (num,)
    ).fetchone()[0]

    if count >= cap:
        await state.clear()
        return await m.answer("❌ нет мест")

    cur.execute(
        "INSERT INTO players VALUES (?,?,0)",
        (num, m.from_user.id)
    )
    conn.commit()

    await state.clear()

    await m.answer(
        f"🎟 зарегистрирован\n\n"
        f"💰 К оплате: {price}₽\n"
        f"💳 Карта: {card}\n\n"
        f"📸 отправьте чек"
    )

# ================= PAYMENT =================

@dp.message(F.photo)
async def check_payment(m: Message):
    row = cur.execute("""
        SELECT tour FROM players
        WHERE user_id=? AND paid=0
        ORDER BY rowid DESC LIMIT 1
    """, (m.from_user.id,)).fetchone()

    if not row:
        return

    tour = row[0]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ принять", callback_data=f"pay_ok:{tour}:{m.from_user.id}"),
            InlineKeyboardButton(text="❌ отклонить", callback_data=f"pay_no:{tour}:{m.from_user.id}")
        ]
    ])

    for owner in OWNERS:
        await bot.send_photo(
            owner,
            m.photo[-1].file_id,
            caption=f"💳 ЧЕК #{tour}\nUser: {m.from_user.id}",
            reply_markup=kb
        )

    await m.answer("⏳ чек отправлен")

@dp.callback_query(F.data.startswith("pay_ok"))
async def pay_ok(c: CallbackQuery):
    _, tour, uid = c.data.split(":")

    cur.execute("""
        UPDATE players SET paid=1
        WHERE tour=? AND user_id=?
    """, (int(tour), int(uid)))

    conn.commit()

    await bot.send_message(int(uid), "✅ оплата принята")
    await c.answer("ok")

@dp.callback_query(F.data.startswith("pay_no"))
async def pay_no(c: CallbackQuery):
    _, tour, uid = c.data.split(":")

    await bot.send_message(
        int(uid),
        "❌ чек не принят, отправьте корректный"
    )

    await c.answer("rejected")

# ================= ADMIN =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if c.from_user.id not in OWNERS:
        return await c.answer("⛔", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ создать", callback_data="create")],
        [InlineKeyboardButton(text="📋 турниры", callback_data="adm_list")],
        [InlineKeyboardButton(text="👥 игроки", callback_data="adm_players")],
        [InlineKeyboardButton(text="🗑 удалить", callback_data="delete_menu")],
        [InlineKeyboardButton(text="🏠 рума", callback_data="room")]
    ])

    await c.message.answer("⚙ ADMIN", reply_markup=kb)

# ================= CREATE =================

@dp.callback_query(F.data == "create")
async def create(c: CallbackQuery, state: FSMContext):
    if c.from_user.id not in OWNERS:
        return

    await state.set_state(CreateFSM.data)
    await c.message.answer("номер цена лимит карта старт(сек)")

@dp.message(CreateFSM.data)
async def create_save(m: Message, state: FSMContext):
    try:
        n, p, cap, card, t = m.text.split()

        cur.execute("""
            INSERT OR REPLACE INTO tournaments
            VALUES (?,?,?,?,?,?,0)
        """, (
            int(n),
            int(p),
            int(cap),
            card,
            "",
            int(time.time()) + int(t)
        ))

        conn.commit()
        await m.answer("✅ создано")

    except:
        await m.answer("❌ формат неверный")

    await state.clear()

# ================= DELETE =================

@dp.callback_query(F.data == "delete_menu")
async def delete_menu(c: CallbackQuery):
    rows = cur.execute("SELECT number, price FROM tournaments").fetchall()

    kb = []
    for n, p in rows:
        kb.append([
            InlineKeyboardButton(text=f"#{n} | {p}₽ ❌", callback_data=f"del:{n}")
        ])

    await c.message.answer("🗑 удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("del:"))
async def delete_t(c: CallbackQuery):
    num = int(c.data.split(":")[1])

    cur.execute("DELETE FROM tournaments WHERE number=?", (num,))
    cur.execute("DELETE FROM players WHERE tour=?", (num,))
    conn.commit()

    await c.answer("удалено", show_alert=True)
    await c.message.edit_text("🗑 удалено")

# ================= ROOM =================

async def send_room(tour, room):
    users = cur.execute("""
        SELECT user_id FROM players
        WHERE tour=? AND paid=1
    """, (tour,)).fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], f"🏁 RUМА #{tour}\n\n{room}")
        except:
            pass

class RoomFSM(StatesGroup):
    data = State()

@dp.callback_query(F.data == "room")
async def room(c: CallbackQuery, state: FSMContext):
    await state.set_state(RoomFSM.data)
    await c.message.answer("номер + рума")

@dp.message(RoomFSM.data)
async def room_save(m: Message, state: FSMContext):
    n, room = m.text.split(maxsplit=1)

    cur.execute("""
        UPDATE tournaments
        SET room=?, room_sent=1
        WHERE number=?
    """, (room, int(n)))

    conn.commit()

    await send_room(int(n), room)

    await state.clear()
    await m.answer("🏁 отправлено")

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
