import asyncio
import os
import threading
from flask import Flask
from curl_cffi import requests as cffi_requests
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "ЗАГЛУШКА")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Мини-страничка (пусть будет)
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает и ищет вакансии! 🚀"

def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 7860)))

threading.Thread(target=run_web_server, daemon=True).start()

def search_hh_sync(query: str, limit: int = 3):
    url = "https://api.hh.ru/vacancies"
    params = {"text": query, "per_page": limit}
    resp = cffi_requests.get(url, params=params, impersonate="chrome", timeout=15)
    if resp.status_code != 200:
        print(f"hh.ru статус {resp.status_code}: {resp.text[:300]}")
        return [], f"Ошибка hh.ru: статус {resp.status_code}"
    data = resp.json()
    results = []
    for v in data.get("items", []):
        salary = "Не указана"
        if v.get("salary"):
            s = v["salary"]
            fr, to = s.get("from"), s.get("to")
            cur = s.get("currency", "RUB")
            if fr and to: salary = f"{fr} - {to} {cur}"
            elif fr: salary = f"от {fr} {cur}"
            elif to: salary = f"до {to} {cur}"
        results.append({
            "title": v.get("name", "Не указано"),
            "company": v.get("employer", {}).get("name", "Не указано"),
            "salary": salary,
            "city": v.get("area", {}).get("name", "Не указан"),
            "url": v.get("alternate_url", ""),
        })
    return results, None

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! 👋\n"
        "Я бот для поиска работы. Введи ключевое слово для поиска.\n"
        "(например: бизнес-аналитик, python, менеджер)"
    )

@router.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if not query:
        return

    status_msg = await message.answer("⏳ Ищу вакансии на hh.ru...")

    results, error = await asyncio.to_thread(search_hh_sync, query)

    if error:
        await status_msg.edit_text(f"❌ {error}")
        return

    if not results:
        await status_msg.edit_text("😕 Ничего не найдено. Попробуй другой запрос.")
        return

    await status_msg.edit_text(f"✅ Готово! Найдено на hh.ru: {len(results)}")

    for job in results:
        text = (
            f"💼 <b>{job['title']}</b>\n"
            f"🏢 {job['company']}\n"
            f"📍 {job['city']}\n"
            f"💰 {job['salary']}\n"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Смотреть вакансию", url=job["url"])]
        ])
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

async def main():
    print("✅ Бот запущен на сервере!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())