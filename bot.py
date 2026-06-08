import os
import asyncio
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# =====================
# ENV
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =====================
# DB
# =====================
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS tournaments (
id INTEGER PRIMARY KEY AUTOINCREMENT,
number INTEGER,
price INTEGER,
max_players INTEGER,
start_time TEXT,
room TEXT DEFAULT '',
status TEXT DEFAULT 'REG'
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS players (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
tournament INTEGER,
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


# =====================
# ADMIN CHECK
# =====================
def is_admin(uid):
    return uid in ADMIN_IDS


def is_banned(uid):
    cur.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,))
    return cur.fetchone() is not None


# =====================
# KEYBOARDS
# =====================
def main_kb(uid):
    kb = [
        [KeyboardButton(text="🎮 Турниры")],
        [KeyboardButton(text="👤 Моя статистика")]
    ]
    if is_admin(uid):
        kb.append([KeyboardButton(text="⚙ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Турниры")],
            [KeyboardButton(text="➕ Создать турнир")],
            [KeyboardButton(text="🔗 Рума")],
            [KeyboardButton(text="🚫 Бан")],
            [KeyboardButton(text="🗑 Удалить турнир")],
            [KeyboardButton(text="🏠 Назад")]
        ],
        resize_keyboard=True
    )


# =====================
# STATE
# =====================
user_state = {}


# =====================
# START
# =====================
@dp.message(CommandStart())
async def start(message: types.Message):
    if is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы")

    await message.answer("🏠 Главное меню", reply_markup=main_kb(message.from_user.id))


# =====================
# USER MENU
# =====================
@dp.message(F.text == "🎮 Турниры")
async def tours(message: types.Message):
    cur.execute("SELECT number, price, max_players, status FROM tournaments")
    data = cur.fetchall()

    text = "🏆 Турниры:\n\n"
    for t in data:
        number, price, maxp, status = t
        cur.execute("SELECT COUNT(*) FROM players WHERE tournament=?", (number,))
        count = cur.fetchone()[0]
        text += f"#{number} | {price}₽ | {count}/{maxp} | {status}\n"

    await message.answer(text)


@dp.message(F.text == "👤 Моя статистика")
async def stats(message: types.Message):
    cur.execute("SELECT tournament FROM players WHERE user_id=?", (message.from_user.id,))
    data = cur.fetchall()

    text = "👤 Твои турниры:\n\n"
    for d in data:
        text += f"🏆 #{d[0]}\n"

    await message.answer(text or "Нет данных")


# =====================
# ADMIN PANEL
# =====================
@dp.message(F.text == "⚙ Админ панель")
async def admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⚙ Админ панель", reply_markup=admin_kb())


@dp.message(F.text == "🏠 Назад")
async def back(message: types.Message):
    await message.answer("🏠 Главное меню", reply_markup=main_kb(message.from_user.id))


# =====================
# CREATE TOURNAMENT
# =====================
@dp.message(F.text == "➕ Создать турнир")
async def create(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    user_state[message.from_user.id] = "create"
    await message.answer("Введите: номер цена макс_игроков время")


# =====================
# ROOM
# =====================
@dp.message(F.text == "🔗 Рума")
async def room(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    user_state[message.from_user.id] = "room"
    await message.answer("Введите: номер и ссылку")


# =====================
# BAN
# =====================
@dp.message(F.text == "🚫 Бан")
async def ban(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    user_state[message.from_user.id] = "ban"
    await message.answer("Введите user_id")


# =====================
# DELETE TOURNAMENT
# =====================
@dp.message(F.text == "🗑 Удалить турнир")
async def delete(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    user_state[message.from_user.id] = "delete"
    await message.answer("Введите номер турнира")


# =====================
# JOIN + PHOTO CHECK + ADMIN APPROVE FLOW
# =====================
@dp.message(F.photo)
async def photo(message: types.Message):
    if is_banned(message.from_user.id):
        return

    cur.execute("SELECT MAX(number) FROM tournaments")
    tour = cur.fetchone()[0]

    if not tour:
        return

    # save receipt
    cur.execute(
        "INSERT INTO players (user_id, tournament, receipt) VALUES (?,?,?)",
        (message.from_user.id, tour, message.photo[-1].file_id)
    )
    conn.commit()

    for admin in ADMIN_IDS:
        await bot.send_photo(
            admin,
            message.photo[-1].file_id,
            caption=f"🧾 Заявка\nUser: {message.from_user.id}\nTour: {tour}"
        )


# =====================
# ADMIN ACTIONS
# =====================
@dp.message()
async def router(message: types.Message):
    uid = message.from_user.id
    text = message.text

    if is_banned(uid):
        return

    if uid in user_state:

        state = user_state[uid]

        # CREATE
        if state == "create":
            number, price, maxp, time = text.split()
            cur.execute(
                "INSERT INTO tournaments (number, price, max_players, start_time) VALUES (?,?,?,?)",
                (int(number), int(price), int(maxp), time)
            )
            conn.commit()
            user_state.pop(uid)
            return await message.answer("✅ Турнир создан")

        # ROOM
        if state == "room":
            number, link = text.split(maxsplit=1)
            cur.execute("UPDATE tournaments SET room=?, status='READY' WHERE number=?",
                        (link, int(number)))
            conn.commit()
            user_state.pop(uid)
            return await message.answer("🔗 Рума добавлена")

        # BAN
        if state == "ban":
            cur.execute("INSERT OR IGNORE INTO bans VALUES (?)", (int(text),))
            conn.commit()
            user_state.pop(uid)
            return await message.answer("🚫 Забанен")

        # DELETE
        if state == "delete":
            cur.execute("DELETE FROM tournaments WHERE number=?", (int(text),))
            cur.execute("DELETE FROM players WHERE tournament=?", (int(text),))
            conn.commit()
            user_state.pop(uid)
            return await message.answer("🗑 Удалён")


# =====================
# WEBHOOK
# =====================
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)


async def on_shutdown(app):
    await bot.delete_webhook()


def create_app():
    app = web.Application()

    SimpleRequestHandler(dp, bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
