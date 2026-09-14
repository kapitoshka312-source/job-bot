import asyncio
import os
import threading
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from flask import Flask
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "ЗАГЛУШКА")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

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

# ========== СОСТОЯНИЯ (FSM) ==========
class SearchStates(StatesGroup):
    waiting_city = State()
    waiting_custom_city = State()
    waiting_format = State()
    waiting_fresh = State()

# ========== КЛАВИАТУРЫ ==========
KB_CITY = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Любой город", callback_data="city:any"),
     InlineKeyboardButton(text="Москва", callback_data="city:Москва")],
    [InlineKeyboardButton(text="Санкт-Петербург", callback_data="city:Санкт-Петербург"),
     InlineKeyboardButton(text="Свой город ✏️", callback_data="city:custom")],
])

KB_FORMAT = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Любой формат", callback_data="fmt:any"),
     InlineKeyboardButton(text="🏠 Удалённо", callback_data="fmt:remote")],
    [InlineKeyboardButton(text="🏢 Офис", callback_data="fmt:office"),
     InlineKeyboardButton(text="🔀 Гибрид", callback_data="fmt:hybrid")],
])

KB_FRESH = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="24 часа", callback_data="fresh:1"),
     InlineKeyboardButton(text="3 дня", callback_data="fresh:3"),
     InlineKeyboardButton(text="Неделя", callback_data="fresh:7")],
    [InlineKeyboardButton(text="Месяц", callback_data="fresh:30"),
     InlineKeyboardButton(text="Любая дата", callback_data="fresh:any")],
])

# ========== ПАРСИНГ ХАБР КАРЬЕРЫ ==========
async def search_habr(query: str):
    url = "https://career.habr.com/vacancies"
    params = {"q": query}
    print(f"🔍 Запрос к Хабр Карьере: {query}")
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as s:
            async with s.get(url, params=params) as r:
                print(f"📥 Статус ответа: {r.status}")
                if r.status != 200:
                    return [], f"Ошибка Хабр Карьеры: статус {r.status}"
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.vacancy-card")
        print(f"🃏 Найдено карточек: {len(cards)}")

        results = []
        for c in cards:
            title_tag = c.select_one("div.vacancy-card__title a.vacancy-card__title-link")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            url_v = "https://career.habr.com" + href if href.startswith("/") else href

            comp_tag = c.select_one("div.vacancy-card__company a.link-comp")
            company = comp_tag.get_text(strip=True) if comp_tag else "Не указано"

            # Зарплата
            salary_box = c.select_one("div.vacancy-card__salary")
            salary = "Не указана"
            if salary_box:
                real = salary_box.select_one("b") or salary_box.select_one("span.salary")
                if real:
                    salary = real.get_text(strip=True)
                else:
                    hint = salary_box.select_one("span.tooltip")
                    if hint:
                        salary = "~ " + hint.get_text(strip=True)

            # Дата публикации
            days_ago = 999
            time_tag = c.select_one("time")
            if time_tag and time_tag.get("datetime"):
                try:
                    dt = datetime.fromisoformat(time_tag["datetime"])
                    days_ago = (datetime.now(dt.tzinfo) - dt).days
                except Exception:
                    pass

            # Чипы: город / формат / грейд (по иконкам)
            city = "Не указан"
            work_format = "Не указан"
            grade = ""
            for ch in c.select("div.vacancy-card__meta div.basic-chip"):
                use = ch.select_one("use")
                href_icon = (use.get("xlink:href") or use.get("href") or "") if use else ""
                txt = ch.get_text(strip=True)
                if "#placemark" in href_icon:
                    city = txt
                elif "#format" in href_icon:
                    work_format = txt
                elif "#grade" in href_icon:
                    grade = txt

            results.append({
                "title": title, "company": company, "salary": salary,
                "city": city, "work_format": work_format, "grade": grade,
                "days_ago": days_ago, "url": url_v,
            })
        return results, None
    except Exception as e:
        print(f"💥 Исключение: {e}")
        return [], f"Сбой Хабр Карьеры: {e}"

# ========== ФИЛЬТРЫ ==========
def apply_filters(items, city, fmt, days):
    out = []
    for it in items:
        if city != "any" and city.lower() not in it["city"].lower():
            continue
        if fmt == "remote" and "удалённо" not in it["work_format"].lower():
            continue
        if fmt == "office" and "офис" not in it["work_format"].lower():
            continue
        if fmt == "hybrid" and "гибрид" not in it["work_format"].lower():
            continue
        if days != "any" and it["days_ago"] > int(days):
            continue
        out.append(it)
    return out

def human_date(days):
    if days == 0: return "сегодня"
    if days == 1: return "вчера"
    if days < 999: return f"{days} дн. назад"
    return "дата неизвестна"

# ========== ХЕНДЛЕРЫ ==========
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! 👋\n"
        "Я бот поиска вакансий на <b>Хабр Карьере</b> с фильтрами.\n\n"
        "Напиши, кого ищешь (например: <code>аналитик</code>),\n"
        "а дальше я спрошу город, формат и свежесть вакансий.\n\n"
        "Команда /cancel — сбросить текущий поиск.",
        parse_mode="HTML"
    )

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔄 Поиск сброшен. Напиши новый запрос.")

# Свой город текстом
@router.message(SearchStates.waiting_custom_city, F.text)
async def custom_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await state.set_state(SearchStates.waiting_format)
    await message.answer("🏢 Формат работы?", reply_markup=KB_FORMAT)

# Главный вход: любой текст = новый запрос
@router.message(F.text)
async def start_search(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is not None:
        return  # мы в середине диалога — текст обрабатывают другие хендлеры
    await state.clear()
    await state.update_data(query=message.text.strip(), city="any", fmt="any")
    await state.set_state(SearchStates.waiting_city)
    await message.answer("📍 Выбери город:", reply_markup=KB_CITY)

@router.callback_query(F.data.startswith("city:"))
async def cb_city(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(SearchStates.waiting_custom_city)
        await callback.message.edit_text("✏️ Напиши свой город:")
        await callback.answer()
        return
    await state.update_data(city=value)
    await state.set_state(SearchStates.waiting_format)
    await callback.message.edit_text("🏢 Формат работы?", reply_markup=KB_FORMAT)
    await callback.answer()

@router.callback_query(F.data.startswith("fmt:"))
async def cb_format(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fmt=callback.data.split(":", 1)[1])
    await state.set_state(SearchStates.waiting_fresh)
    await callback.message.edit_text("📅 Насколько свежие вакансии показывать?", reply_markup=KB_FRESH)
    await callback.answer()

@router.callback_query(F.data.startswith("fresh:"))
async def cb_fresh(callback: CallbackQuery, state: FSMContext):
    days = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    await callback.message.edit_text("⏳ Ищу вакансии с учётом фильтров...")
    await callback.answer()

    results, error = await search_habr(data.get("query", ""))
    if error:
        await callback.message.edit_text(f"❌ {error}")
        return

    filtered = apply_filters(results, data.get("city", "any"), data.get("fmt", "any"), days)[:6]
    print(f"✅ После фильтров: {len(filtered)}")

    if not filtered:
        await callback.message.edit_text(
            "😕 Ничего не найдено с такими фильтрами.\n"
            "Попробуй ослабить фильтры (другой город, любая дата)."
        )
        return

    await callback.message.edit_text(f"✅ Найдено: {len(filtered)}")

    for job in filtered:
        meta = " • ".join(x for x in [job["grade"], job["work_format"], job["city"]] if x and x != "Не указан")
        text = (
            f"💼 <b>{job['title']}</b>\n"
            f"🏢 {job['company']}\n"
            f"💰 {job['salary']}\n"
            f"📅 Опубликовано: {human_date(job['days_ago'])}\n"
            f"ℹ️ {meta}\n"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Смотреть на Хабр Карьере", url=job["url"])]
        ])
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

async def main():
    print("✅ Бот Хабр Карьера запущен!")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка polling: {e}")
        if "Conflict" in str(e):
            import sys
            sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())