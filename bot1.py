import asyncio
import os
import threading
import aiohttp
from bs4 import BeautifulSoup
from flask import Flask
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

# Мини-сервер (нужен для облачных платформ, чтобы не усыпляли)
app = Flask(__name__)
@app.route('/')
def home():
    return "Бот Хабр Карьера работает! 🚀"

def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 7860)))

threading.Thread(target=run_web_server, daemon=True).start()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

async def search_habr(query: str, limit: int = 5):
    url = "https://career.habr.com/vacancies"
    params = {"q": query}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return [], f"Ошибка Хабр Карьеры: статус {r.status}"
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.vacancy-card")[:limit]

        results = []
        for c in cards:
            # Название
            title_tag = c.select_one("div.vacancy-card__title a.vacancy-card__title-link")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            url_v = "https://career.habr.com" + href if href.startswith("/") else href

            # Компания
            comp_tag = c.select_one("div.vacancy-card__company a.link-comp")
            company = comp_tag.get_text(strip=True) if comp_tag else "Не указано"

            # Зарплата
            salary_box = c.select_one("div.vacancy-card__salary")
            salary = "Не указана"
            if salary_box:
                # Реальная зарплата (если есть <b>)
                real = salary_box.select_one("b") or salary_box.select_one("span.salary")
                if real:
                    salary = real.get_text(strip=True)
                else:
                    # Предсказанная зарплата
                    hint = salary_box.select_one("span.tooltip")
                    if hint:
                        salary = "~ " + hint.get_text(strip=True)

            # Мета-информация: уровень, город, формат
            chips = c.select("div.vacancy-card__meta div.basic-chip")
            meta_parts = []
            for ch in chips:
                txt = ch.select_one(".chip-with-icon__text")
                if txt:
                    meta_parts.append(txt.get_text(strip=True))

            city = next((x for x in meta_parts if x not in ["Junior", "Middle", "Senior", "Можно удалённо", "В офисе", "Гибрид"]), "Не указан")

            results.append({
                "title": title,
                "company": company,
                "salary": salary,
                "city": city,
                "meta": " • ".join(meta_parts),
                "url": url_v,
            })
        return results, None
    except Exception as e:
        return [], f"Сбой Хабр Карьеры: {e}"

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! 👋\n"
        "Я бот для поиска вакансий на <b>Хабр Карьере</b>.\n"
        "Напиши, кого ищешь:\n"
        "например: <code>python</code>, <code>аналитик</code>, <code>менеджер</code>",
        parse_mode="HTML"
    )

@router.message(F.text)
async def handle_search(message: Message):
    query = message.text.strip()
    if not query:
        return

    status_msg = await message.answer("⏳ Ищу вакансии на Хабр Карьере...")
    results, error = await search_habr(query, limit=5)

    if error:
        await status_msg.edit_text(f"❌ {error}")
        return
    if not results:
        await status_msg.edit_text("😕 Ничего не найдено. Попробуй другой запрос.")
        return

    await status_msg.edit_text(f"✅ Готово! Найдено: {len(results)}")

    for job in results:
        text = (
            f"💼 <b>{job['title']}</b>\n"
            f"🏢 {job['company']}\n"
            f"📍 {job['city']}\n"
            f"💰 {job['salary']}\n"
            f"ℹ️ {job['meta']}\n"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Смотреть на Хабр Карьере", url=job["url"])]
        ])
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

async def main():
    print("✅ Бот Хабр Карьера запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())