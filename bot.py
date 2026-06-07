import asyncio
import logging
import os
import aiosqlite

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

# ================= CACHE =================

CACHE = {
    "tournaments": [],
    "players_count": {}
}

# ================= FSM =================

class JoinFSM(StatesGroup):
    tour = State()

class CreateFSM(StatesGroup):
    number = State()
    price = State()
    max_players = State()

class RoomFSM(StatesGroup):
    data = State()

# ================= DB =================

DB_PATH = "db.sqlite3"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (
            number INTEGER PRIMARY KEY,
            price INTEGER,
            max_players INTEGER,
            room TEXT DEFAULT ''
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS players (
            tour INTEGER,
            user_id INTEGER,
            UNIQUE(tour, user_id)
        )
        """)
        await db.commit()

# ================= CACHE LOADER =================

async def load_cache():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT number, price, max_players, room FROM tournaments")
        CACHE["tournaments"] = await cur.fetchall()

        cur = await db.execute("SELECT tour, COUNT(*) FROM players GROUP BY tour")
        CACHE["players_count"] = dict(await cur.fetchall())

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

# ================= FAST HANDLERS =================

@dp.message(F.text == "/start")
async def start(m: Message):
    await m.answer("🎮 FAST BOT", reply_markup=menu(is_owner(m.from_user.id)))

# ================= LIST (CACHE ONLY) =================

@dp.callback_query(F.data == "list")
async def list_t(c: CallbackQuery):
    if not CACHE["tournaments"]:
        return await c.message.answer("Нет турниров")

    text = "🎮 Турниры:\n\n"
    for n, p, mpx, r in CACHE["tournaments"]:
        count = CACHE["players_count"].get(n, 0)
        text += f"#{n} | {p}₽ | {count}/{mpx} | {'🟢' if r else '🔴'}\n"

    await c.message.answer(text)

# ================= JOIN FAST =================

@dp.callback_query(F.data == "join")
async def join(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Номер турнира")
    await state.set_state(JoinFSM.tour)

@dp.message(JoinFSM.tour)
async def join_handler(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ число")

    num = int(m.text)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT max_players FROM tournaments WHERE number=?", (num,))
        tour = await cur.fetchone()

        if not tour:
            return await m.answer("❌ нет турнира")

        cur = await db.execute(
            "SELECT 1 FROM players WHERE tour=? AND user_id=?",
            (num, m.from_user.id)
        )
        if await cur.fetchone():
            return await m.answer("⚠️ уже в турнире")

        if CACHE["players_count"].get(num, 0) >= tour[0]:
            return await m.answer("❌ мест нет")

        await db.execute("INSERT INTO players VALUES (?,?)", (num, m.from_user.id))
        await db.commit()

    CACHE["players_count"][num] = CACHE["players_count"].get(num, 0) + 1
    await state.clear()

    await m.answer("🎟 записан")

# ================= LEAVE FAST =================

@dp.callback_query(F.data == "leave")
async def leave(c: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM players WHERE user_id=?", (c.from_user.id,))
        await db.commit()

    CACHE["players_count"] = {}
    await load_cache()

    await c.message.answer("🚪 вышел")

# ================= ADMIN CHECK =================

@dp.callback_query(F.data == "admin")
async def admin(c: CallbackQuery):
    if not is_owner(c.from_user.id):
        return await c.answer("no", show_alert=True)
    await c.message.answer("⚙ ADMIN")

# ================= WEBHOOK =================

async def handle(request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="ok")

async def index(request):
    return web.Response(text="FAST BOT OK")

# ================= WEBHOOK WATCHER =================

async def webhook_watcher():
    while True:
        try:
            info = await bot.get_webhook_info()
            if info.url != WEBHOOK_URL:
                await bot.set_webhook(WEBHOOK_URL)
                print("🔁 webhook fixed")
        except:
            pass
        await asyncio.sleep(30)

# ================= STARTUP =================

async def on_startup(app):
    await init_db()
    await load_cache()

    await bot.set_webhook(WEBHOOK_URL)

    asyncio.create_task(webhook_watcher())

# ================= APP =================

app = web.Application()
app.router.add_post("/webhook", handle)
app.router.add_get("/", index)

app.on_startup.append(on_startup)

# ================= RUN =================

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
