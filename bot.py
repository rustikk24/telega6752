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


# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")

OWNER_IDS = set(int(x) for x in os.getenv("OWNERS", "").split(",") if x.strip().isdigit())
FALLBACK_ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")

if not TOKEN:
    raise ValueError("BOT_TOKEN missing")
if not BASE_URL:
    raise ValueError("BASE_URL missing")

CHANNEL = "@ovqk_fun"
WEBHOOK_URL = BASE_URL + "/webhook"

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ================= ADMIN =================

def is_admin(user_id: int):
    return user_id in OWNER_IDS or user_id == FALLBACK_ADMIN_ID


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Турниры", callback_data="adm_tournaments")],
        [InlineKeyboardButton(text="👥 Игроки", callback_data="adm_players")],
        [InlineKeyboardButton(text="➕ Создать", callback_data="adm_create")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_delete")],
        [InlineKeyboardButton(text="🏠 Рума", callback_data="adm_room")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
    ])


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

conn.commit()


# ================= FSM =================

class AdminCreateFSM(StatesGroup):
    data = State()

class AdminRoomFSM(StatesGroup):
    data = State()


# ================= START =================

@dp.message(F.text == "/start")
async def start(m: Message):
    cur.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    conn.commit()

    await m.answer("🎮 MENU\n\nНапиши /admin для панели")


# ================= ADMIN ENTRY =================

@dp.message(F.text == "/admin")
async def admin(m: Message):

    if not is_admin(m.from_user.id):
        return await m.answer("⛔ нет доступа")

    await m.answer("⚙ ADMIN PANEL", reply_markup=admin_kb())


# ================= ADMIN PANEL CALLBACK =================

@dp.callback_query(F.data.startswith("adm"))
async def admin_panel(c: CallbackQuery, state: FSMContext):

    if not is_admin(c.from_user.id):
        return await c.answer("⛔ нет доступа", show_alert=True)

    data = c.data

    # ---------- TOURNAMENTS ----------
    if data == "adm_tournaments":
        rows = cur.execute("SELECT number, price, max_players, room_sent FROM tournaments").fetchall()

        text = "🎮 ТУРНИРЫ:\n\n"
        for n, p, cap, room in rows:
            text += f"#{n} | {p}₽ | {cap} мест | {'🏁' if room else '🔴'}\n"

        return await c.message.answer(text)


    # ---------- PLAYERS ----------
    if data == "adm_players":
        rows = cur.execute("SELECT tour, user_id, paid FROM players").fetchall()

        text = "👥 ИГРОКИ:\n\n"
        for t, u, p in rows:
            text += f"#{t} | {u} | {'✅' if p else '❌'}\n"

        return await c.message.answer(text)


    # ---------- CREATE ----------
    if data == "adm_create":
        await state.set_state(AdminCreateFSM.data)
        return await c.message.answer(
            "Создание турнира:\n"
            "номер цена лимит карта время(HH:MM)"
        )


    # ---------- DELETE ----------
    if data == "adm_delete":
        rows = cur.execute("SELECT number FROM tournaments").fetchall()

        kb = [[InlineKeyboardButton(text=f"❌ #{n}", callback_data=f"del:{n[0]}")] for n in rows]

        return await c.message.answer(
            "Удалить турнир:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )


    # ---------- ROOM ----------
    if data == "adm_room":
        await state.set_state(AdminRoomFSM.data)
        return await c.message.answer("Введите:\nномер ссылка_румы")


    # ---------- CLOSE ----------
    if data == "adm_close":
        return await c.message.delete()


# ================= CREATE =================

@dp.message(AdminCreateFSM.data)
async def create_tournament(m: Message, state: FSMContext):

    try:
        parts = m.text.split()

        n = int(parts[0])
        p = int(parts[1])
        cap = int(parts[2])
        time_str = parts[-1]
        card = " ".join(parts[3:-1])

        h, mm = map(int, time_str.split(":"))
        now = datetime.now()
        start = now.replace(hour=h, minute=mm, second=0, microsecond=0)

        if start < now:
            start += timedelta(days=1)

        cur.execute("""
            INSERT OR REPLACE INTO tournaments
            VALUES (?,?,?,?,?,?,0)
        """, (n, p, cap, card, "", int(start.timestamp())))

        conn.commit()

        await m.answer("✅ создано")

    except:
        await m.answer("❌ ошибка")

    await state.clear()


# ================= ROOM =================

@dp.message(AdminRoomFSM.data)
async def set_room(m: Message, state: FSMContext):

    try:
        num, link = m.text.split(maxsplit=1)

        cur.execute(
            "UPDATE tournaments SET room=?, room_sent=1 WHERE number=?",
            (link, int(num))
        )

        conn.commit()

        players = cur.execute(
            "SELECT user_id FROM players WHERE tour=?",
            (int(num),)
        ).fetchall()

        for p in players:
            try:
                await bot.send_message(p[0], f"🏠 Рума #{num}\n{link}")
            except:
                pass

        await m.answer("✅ румa отправлена")

    except:
        await m.answer("❌ ошибка")

    await state.clear()


# ================= DELETE =================

@dp.callback_query(F.data.startswith("del:"))
async def delete(c: CallbackQuery):

    if not is_admin(c.from_user.id):
        return

    num = int(c.data.split(":")[1])

    cur.execute("DELETE FROM tournaments WHERE number=?", (num,))
    cur.execute("DELETE FROM players WHERE tour=?", (num,))
    conn.commit()

    await c.answer("удалено")
    await c.message.edit_text("🗑 удалено")


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
