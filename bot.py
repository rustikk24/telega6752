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

CHANNEL = "@ovqk_fun"
WEBHOOK_URL = (BASE_URL or "") + "/webhook"

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
    paid INTEGER DEFAULT 0
)
""")

conn.commit()

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

    if not await is_subscribed(m.from_user.id):
        return await m.answer(
            "❌ Подпишись на канал чтобы использовать бота:",
            reply_markup=sub_keyboard()
        )

    await m.answer("🎮 MENU", reply_markup=menu())

# ================= CHECK SUB =================

@dp.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    if await is_subscribed(c.from_user.id):
        await c.message.edit_text("✅ доступ разрешён")
        await c.message.answer("🎮 MENU", reply_markup=menu())
    else:
        await c.answer("❌ вы не подписаны", show_alert=True)

# ================= ADMIN =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if c.from_user.id not in OWNERS:
        return await c.answer("⛔ нет доступа", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ создать", callback_data="create")],
        [InlineKeyboardButton(text="🎮 турниры", callback_data="adm_tournaments")],
        [InlineKeyboardButton(text="👥 игроки", callback_data="adm_players")],
        [InlineKeyboardButton(text="🗑 удалить", callback_data="delete_menu")],
        [InlineKeyboardButton(text="🏠 рума", callback_data="room")]
    ])

    await c.message.answer("⚙ ADMIN PANEL", reply_markup=kb)

# ================= TOURNAMENTS =================

@dp.callback_query(F.data == "adm_tournaments")
async def adm_tournaments(c: CallbackQuery):
    rows = cur.execute("SELECT number, price, max_players, room_sent FROM tournaments").fetchall()

    text = "🎮 ТУРНИРЫ:\n\n"
    for n, p, cap, sent in rows:
        status = "🏁 рума есть" if sent else "🔴 без рума"
        text += f"#{n} | {p}₽ | {cap} | {status}\n"

    await c.message.answer(text)

# ================= PLAYERS =================

@dp.callback_query(F.data == "adm_players")
async def adm_players(c: CallbackQuery):
    rows = cur.execute("SELECT tour, user_id, paid FROM players").fetchall()

    text = "👥 ИГРОКИ:\n\n"
    for t, u, p in rows:
        text += f"#{t} | {u} | {'✅' if p else '❌'}\n"

    await c.message.answer(text)

# ================= CREATE =================

@dp.callback_query(F.data == "create")
async def create(c: CallbackQuery, state: FSMContext):
    if c.from_user.id not in OWNERS:
        return

    await state.set_state(CreateFSM.data)
    await c.message.answer(
        "ФОРМАТ:\n"
        "номер цена лимит карта(16 цифр) время(HH:MM)"
    )

@dp.message(CreateFSM.data)
async def create_save(m: Message, state: FSMContext):
    try:
        parts = m.text.split()

        n = int(parts[0])
        p = int(parts[1])
        cap = int(parts[2])
        time_str = parts[-1]
        card = " ".join(parts[3:-1])

        now = datetime.now()
        h, mm = map(int, time_str.split(":"))

        start = now.replace(hour=h, minute=mm, second=0, microsecond=0)
        if start < now:
            start += timedelta(days=1)

        start_ts = int(start.timestamp())

        cur.execute("""
            INSERT OR REPLACE INTO tournaments
            VALUES (?,?,?,?,?,?,0)
        """, (n, p, cap, card, "", start_ts))

        conn.commit()
        await m.answer("✅ создано")

    except:
        await m.answer("❌ ошибка формата")

    await state.clear()

# ================= DELETE =================

@dp.callback_query(F.data == "delete_menu")
async def delete_menu(c: CallbackQuery):
    rows = cur.execute("SELECT number, price FROM tournaments").fetchall()

    kb = [[InlineKeyboardButton(text=f"#{n} | {p}₽ ❌", callback_data=f"del:{n}")] for n, p in rows]

    await c.message.answer("🗑 удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("del:"))
async def delete_t(c: CallbackQuery):
    num = int(c.data.split(":")[1])

    cur.execute("DELETE FROM tournaments WHERE number=?", (num,))
    cur.execute("DELETE FROM players WHERE tour=?", (num,))
    conn.commit()

    await c.answer("удалено", show_alert=True)
    await c.message.edit_text("🗑 удалено")

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

    tour = cur.execute("SELECT price, max_players, card FROM tournaments WHERE number=?", (num,)).fetchone()
    if not tour:
        return await m.answer("❌ нет турнира")

    price, cap, card = tour

    count = cur.execute("SELECT COUNT(*) FROM players WHERE tour=?", (num,)).fetchone()[0]
    if count >= cap:
        return await m.answer("❌ нет мест")

    cur.execute("INSERT INTO players VALUES (?,?,0)", (num, m.from_user.id))
    conn.commit()

    await state.clear()

    await m.answer(f"💰 {price}₽\n💳 {card}\n📸 отправьте чек")
# ================= WEBHOOK =================

async def handle(request):

И вставь прямо перед ним вот этот блок:

# ================= USER TOURNAMENTS =================

@dp.callback_query(F.data == "list")
async def list_tournaments(c: CallbackQuery):

    rows = cur.execute("""
        SELECT number, price, max_players, room_sent
        FROM tournaments
    """).fetchall()

    if not rows:
        return await c.message.answer("❌ Турниров нет")

    text = "🎮 Турниры:\n\n"

    for n, p, cap, room in rows:
        status = "🏁 Рума добавлена" if room else "🔴 Без румы"
        text += f"#{n} | {p}₽ | {cap} мест | {status}\n"

    await c.message.answer(text)


# ================= ROOM =================

@dp.callback_query(F.data == "room")
async def room(c: CallbackQuery, state: FSMContext):

    if c.from_user.id not in OWNERS:
        return await c.answer("⛔ нет доступа", show_alert=True)

    await state.set_state(RoomFSM.data)

    await c.message.answer(
        "Введите:\n\n"
        "номер_турнира ссылка_на_руму"
    )


@dp.message(RoomFSM.data)
async def room_save(m: Message, state: FSMContext):

    try:
        num, room_link = m.text.split(maxsplit=1)
        num = int(num)

        cur.execute(
            "UPDATE tournaments SET room=?, room_sent=1 WHERE number=?",
            (room_link, num)
        )

        conn.commit()

        players = cur.execute(
            "SELECT user_id FROM players WHERE tour=?",
            (num,)
        ).fetchall()

        sent = 0

        for player in players:
            try:
                await bot.send_message(
                    player[0],
                    f"🏠 Рума турнира №{num}\n\n{room_link}"
                )
                sent += 1
            except:
                pass

        await m.answer(f"✅ Рума сохранена\n📨 Отправлено: {sent}")

    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")

    await state.clear()
    
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
