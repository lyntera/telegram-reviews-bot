import asyncio
import logging
import sqlite3
import json
import re
import os
from typing import Any, Dict, List
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message, InputMediaPhoto, CallbackQuery
from aiogram.filters.callback_data import CallbackData
from dotenv import load_dotenv

load_dotenv("token.env")
TOKEN = os.getenv("BOT_TOKEN")
ACHAT_ID = int(os.getenv("ACHAT_ID"))
CHANNEL_ID = os.getenv("CHANNEL_ID")
BOT_USERNAME = os.getenv("BOT_USERNAME")

def init_db():
    with sqlite3.connect("reviews.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                content TEXT,
                photos TEXT,
                label TEXT,
                rating INTEGER DEFAULT 5,
                status TEXT DEFAULT 'pending'
            )
        """)
        conn.commit()

class ReviewState(StatesGroup):
    waiting_content = State()
    choosing_rating = State()
    choosing_anon = State()

class AdminAction(CallbackData, prefix="adm"):
    action: str 
    review_id: int

def get_stars(count: int) -> str:
    return "⭐" * count + "☆" * (5 - count)

class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.6):
        self.latency = latency
        self.album_data: Dict[str, List[Message]] = {}

    async def __call__(self, handler, event: Message, data: Dict[str, Any]) -> Any:
        if not event.media_group_id: return await handler(event, data)
        try:
            self.album_data[event.media_group_id].append(event)
            return 
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)
            data["album"] = self.album_data.pop(event.media_group_id)
            return await handler(event, data)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.message.outer_middleware(AlbumMiddleware())

@dp.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✨ <b>Добро пожаловать в Lyntera Reviews!</b>\n\n"
        "Поделитесь вашим отзывом о работе с компанией Lyntera (текст или фото). Мы ценим ваше мнение! 👇",
        parse_mode="HTML"
    )
    await state.set_state(ReviewState.waiting_content)

@dp.message(ReviewState.waiting_content, (F.text | F.photo))
async def handle_review_content(message: Message, state: FSMContext, album: List[Message] = None):
    p_ids = [m.photo[-1].file_id for m in album if m.photo] if album else ([message.photo[-1].file_id] if message.photo else [])
    cap = next((m.caption for m in album if m.caption), "") if album else (message.text or message.caption or "")
    await state.update_data(rev_content=cap, rev_photos=p_ids)
    kb = InlineKeyboardBuilder()
    for i in range(5, 0, -1):
        kb.button(text=f"{i} ⭐", callback_data=f"rate_{i}")
    kb.adjust(5)
    await message.answer("📊 <b>Ваша оценка?</b>\nВыберите количество звезд:", reply_markup=kb.as_markup(), parse_mode="HTML")
    await state.set_state(ReviewState.choosing_rating)

@dp.callback_query(ReviewState.choosing_rating, F.data.startswith("rate_"))
async def handle_rating(callback: CallbackQuery, state: FSMContext):
    rating = int(callback.data.split("_")[1])
    await state.update_data(rev_rating=rating)
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Публично", callback_data="type_pub")
    kb.button(text="🕵️ Анонимно", callback_data="type_ano")
    await callback.message.edit_text(
        f"Вы выбрали: {get_stars(rating)}\n\n🔒 <b>Настройка приватности:</b>\nКак опубликовать отзыв?", 
        reply_markup=kb.as_markup(), 
        parse_mode="HTML"
    )
    await state.set_state(ReviewState.choosing_anon)

@dp.callback_query(ReviewState.choosing_anon, F.data.startswith("type_"))
async def finalize_review(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    is_anon = callback.data == "type_ano"
    label = "🕵️ Анонимно" if is_anon else f"👤 @{callback.from_user.username or callback.from_user.id}"
    rating = data.get('rev_rating', 5)
    with sqlite3.connect("reviews.db") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (user_id, content, photos, label, rating) VALUES (?, ?, ?, ?, ?)",
            (callback.from_user.id, data['rev_content'], json.dumps(data['rev_photos']), label, rating)
        )
        review_id = cursor.lastrowid
        conn.commit()
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Опубликовать", callback_data=AdminAction(action="pub", review_id=review_id))
    kb.button(text="❌ Отклонить", callback_data=AdminAction(action="dec", review_id=review_id))
    kb.adjust(1)
    admin_text = (
        f"💫 <b>Поступил новый отзыв! #{review_id}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Рейтинг:</b> {get_stars(rating)}\n"
        f"<b>Отправитель:</b> {label}\n"
        f"<b>Текст:</b>\n<blockquote>{data['rev_content'] or '—'}</blockquote>"
    )
    if data['rev_photos']:
        media = [InputMediaPhoto(media=data['rev_photos'][0], caption=admin_text, parse_mode="HTML")]
        for p_id in data['rev_photos'][1:]: media.append(InputMediaPhoto(media=p_id))
        await bot.send_media_group(ACHAT_ID, media)
        await bot.send_message(ACHAT_ID, f"⚡️ Управление отзывом #{review_id}:", reply_markup=kb.as_markup())
    else:
        await bot.send_message(ACHAT_ID, admin_text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.message.edit_text("🚀 <b>Спасибо за отзыв!</b>\nОн появится в канале после проверки.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(AdminAction.filter(F.action == "pub"))
async def admin_approve(callback: CallbackQuery, callback_data: AdminAction):
    with sqlite3.connect("reviews.db") as conn:
        row = conn.execute("SELECT user_id, content, photos, label, rating, status FROM reviews WHERE id = ?", (callback_data.review_id,)).fetchone()
    if not row or row[5] != 'pending':
        return await callback.answer("⚠️ Уже обработано или не найдено.")
    u_id, cont, pts_json, label, rating, _ = row
    pts = json.loads(pts_json)
    chan_text = (
        f"📝 <b>Отзыв от {label}</b>\n"
        f"<b>Оценка:</b> {get_stars(rating)}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"<blockquote>{cont}</blockquote>"
    )
    chan_kb = InlineKeyboardBuilder()
    chan_kb.button(text="🤝 Оставить свой отзыв", url=f"https://t.me/{BOT_USERNAME.replace('@', '')}")
    try:
        if pts:
            media = []
            for i, p_id in enumerate(pts):
                if i == 0: media.append(InputMediaPhoto(media=p_id, caption=chan_text, parse_mode="HTML"))
                else: media.append(InputMediaPhoto(media=p_id))
            await bot.send_media_group(CHANNEL_ID, media)
            await bot.send_message(CHANNEL_ID, "👆 <i>Выше представлен отзыв клиента</i>", reply_markup=chan_kb.as_markup(), parse_mode="HTML")
        else: 
            await bot.send_message(CHANNEL_ID, chan_text, parse_mode="HTML", reply_markup=chan_kb.as_markup())
        with sqlite3.connect("reviews.db") as conn:
            conn.execute("UPDATE reviews SET status = 'published' WHERE id = ?", (callback_data.review_id,))
            conn.commit()
        await callback.message.edit_text(f"✅ Опубликован отзыв #{callback_data.review_id}")
        try: await bot.send_message(u_id, "🎉 Готово! Ваш отзыв опубликован в канале.")
        except: pass
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(AdminAction.filter(F.action == "dec"))
async def admin_decline_trigger(callback: CallbackQuery, callback_data: AdminAction):
    await callback.message.answer(f"⚠️ <b>ОТКЛОНЕНИЕ ОТЗЫВА #{callback_data.review_id}</b>\nНапишите причину в <b>ОТВЕТЕ</b> на это сообщение 👇", parse_mode="HTML")
    await callback.answer()

@dp.message(F.chat.id == ACHAT_ID, F.reply_to_message)
async def process_admin_decline_reply(message: Message):
    reply_text = message.reply_to_message.text or ""
    if "⚠️ ОТКЛОНЕНИЕ ОТЗЫВА #" not in reply_text: return
    try:
        review_id = int(re.search(r'#(\d+)', reply_text).group(1))
        with sqlite3.connect("reviews.db") as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT user_id, status FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if not row or row[1] != 'pending': return await message.reply("⚠️ Отзыв уже обработан.")
            user_id = row[0]
            cursor.execute("UPDATE reviews SET status = 'declined' WHERE id = ?", (review_id,))
            conn.commit()
        await bot.send_message(user_id, f"❌ <b>Ваш отзыв отклонен</b>\n\n<b>Причина:</b>\n<blockquote>{message.text}</blockquote>", parse_mode="HTML")
        await message.reply(f"✅ Отказ для отзыва #{review_id} отправлен.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":

    asyncio.run(main())


