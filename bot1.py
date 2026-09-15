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
import re

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "ЗАГЛУШКА")
SUPERJOB_KEY = os.getenv("SUPERJOB_KEY", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

app = Flask(__name__)
@app.route('/')
def home():
    return "Job Search Bot is running! 🚀"

def run_web_server():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 7860)))

threading.Thread(target=run_web_server, daemon=True).start()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

PAGE_SIZE = 8       # вакансий за одну порцию
MAX_RESULTS = 50    # максимум вакансий за один поиск
SEARCH_CACHE = {}   # хранение результатов для кнопки "ещё"

# ========== СОСТОЯНИЯ (FSM) ==========
class SearchStates(StatesGroup):
    waiting_source = State()
    waiting_city = State()
    waiting_custom_city = State()
    waiting_format = State()
    waiting_fresh = State()

# ========== КЛАВИАТУРЫ ==========
KB_SOURCE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔵 Хабр Карьера", callback_data="src:habr"),
     InlineKeyboardButton(text="🟢 SuperJob", callback_data="src:sj")],
    [InlineKeyboardButton(text="🌐 Remote-Job", callback_data="src:remote"),
     InlineKeyboardButton(text="💼 Hirify", callback_data="src:hirify")],
    [InlineKeyboardButton(text="🌍 Искать везде", callback_data="src:all")],
])

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

def more_keyboard(remaining):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"➡️ Показать ещё (осталось {remaining})", callback_data="more")]
    ])

# ========== УТИЛИТЫ ==========
def make_key(item):
    title_norm = re.sub(r'\s+', ' ', item.get("title", "").lower().strip())[:40]
    company = item.get("company", "").lower().strip()[:30]
    return (title_norm, company)

def deduplicate_and_sort(items):
    seen = set()
    unique = []
    for item in items:
        key = make_key(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    unique.sort(key=lambda x: x.get("days_ago", 999))
    print(f"🧹 Дублей убрано: {len(items) - len(unique)}, осталось: {len(unique)}")
    return unique

async def send_vacancy(chat_id, job):
    meta = " • ".join(x for x in [job["grade"], job["work_format"], job["city"]] if x and x != "Не указан" and x != "Можно удалённо")
    if "удалённ" in job["work_format"].lower():
        meta = ("🏠 Удалённо • " + meta) if meta else "🏠 Удалённо"
    elif "офис" in job["work_format"].lower():
        meta = ("🏢 Офис • " + meta) if meta else "🏢 Офис"

    text = (
        f"<i>[{job['source']}]</i>\n"
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company']}\n"
        f"💰 {job['salary']}\n"
        f"📅 {human_date(job['days_ago'])}\n"
        f"ℹ️ {meta}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть вакансию", url=job["url"])]
    ])
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

# ========== ПАРСИНГ ХАБР КАРЬЕРЫ ==========
async def search_habr(query: str):
    url = "https://career.habr.com/vacancies"
    params = {"q": query}
    print(f"🔍 Хабр: {query}")
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return [], f"Хабр: статус {r.status}"
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.vacancy-card")

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

            days_ago = 999
            time_tag = c.select_one("time")
            if time_tag and time_tag.get("datetime"):
                try:
                    dt = datetime.fromisoformat(time_tag["datetime"])
                    days_ago = (datetime.now(dt.tzinfo) - dt).days
                except Exception:
                    pass

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
                "source": "Хабр",
                "title": title, "company": company, "salary": salary,
                "city": city, "work_format": work_format, "grade": grade,
                "days_ago": days_ago, "url": url_v,
            })
        return results, None
    except Exception as e:
        return [], f"Сбой Хабра: {e}"

# ========== ПАРСИНГ SUPERJOB ==========
REMOTE_KEYWORDS = ("удалённ", "удаленн", "remote", "дистанционн")

async def search_superjob(query: str):
    if not SUPERJOB_KEY:
        return [], "SuperJob: не задан ключ API"
    url = "https://api.superjob.ru/2.33/vacancies/"
    params = {"keyword": query, "count": 50}
    headers = {"X-Api-App-Id": SUPERJOB_KEY, "User-Agent": "Mozilla/5.0"}
    print(f"🔍 SuperJob: {query}")
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return [], f"SuperJob: статус {r.status}"
                data = await r.json()

        now = datetime.now().timestamp()
        results = []
        for v in data.get("objects", []):
            title = v.get("profession") or "Не указано"
            company = v.get("firm_name") or (v.get("client", {}) or {}).get("title") or "Не указано"

            p_from = v.get("payment_from") or 0
            p_to = v.get("payment_to") or 0
            cur = (v.get("currency") or "rub").upper()
            if p_from and p_to:
                salary = f"{p_from} - {p_to} {cur}"
            elif p_from:
                salary = f"от {p_from} {cur}"
            elif p_to:
                salary = f"до {p_to} {cur}"
            else:
                salary = "Не указана"

            city = (v.get("town") or {}).get("title", "Не указан")

            date_pub = v.get("date_published") or 0
            days_ago = int((now - date_pub) / 86400) if date_pub else 999

            place = (v.get("place_of_work") or {}).get("title", "").lower()
            description = (v.get("candidat") or "") + " " + (v.get("vacancyRichText") or "")
            description = description.lower()

            if "удаленн" in place or "remote" in place or any(k in description for k in REMOTE_KEYWORDS):
                work_format = "Можно удалённо"
            elif "офис" in place:
                work_format = "В офисе"
            elif "гибрид" in place or "hybrid" in place:
                work_format = "Гибрид"
            else:
                work_format = "Не указан"

            results.append({
                "source": "SuperJob",
                "title": title, "company": company, "salary": salary,
                "city": city, "work_format": work_format, "grade": "",
                "days_ago": days_ago, "url": v.get("link", ""),
            })
        return results, None
    except Exception as e:
        return [], f"Сбой SuperJob: {e}"

# ========== ПАРСИНГ REMOTE-JOB.RU ==========
def parse_remote_date(date_str: str) -> int:
    date_str = date_str.strip().rstrip(',')
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
        "мая": 5, "июня": 6, "июля": 7, "августа": 8,
        "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
    }
    try:
        parts = date_str.split()
        if len(parts) < 3:
            return 999
        day = int(parts[0])
        month = months.get(parts[1].lower(), 0)
        year = int(parts[2])
        if month == 0:
            return 999
        dt = datetime(year, month, day)
        return (datetime.now() - dt).days
    except Exception:
        return 999

async def search_remote_job(query: str):
    url = "https://remote-job.ru/search"
    params = {"search[query]": query, "search[searchType]": "vacancy"}
    print(f"🔍 Remote-Job: {query}")
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return [], f"Remote-Job: статус {r.status}"
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.vacancy_item")
        print(f"🃏 Remote-Job карточек: {len(cards)}")

        results = []
        for c in cards:
            h2 = c.select_one("h2")
            if not h2:
                continue

            title_tag = h2.select_one("a")
            if not title_tag:
                continue

            title = " ".join(title_tag.get_text(strip=True).split())
            href = title_tag.get("href", "")
            url_v = "https://remote-job.ru" + href if href.startswith("/") else href

            date_small = h2.select_one("small")
            date_str = date_small.get_text(strip=True) if date_small else ""
            days_ago = parse_remote_date(date_str)

            company = "Не указано"
            company_small = h2.select("small")
            if len(company_small) > 1:
                company_a = company_small[1].select_one("a")
                if company_a:
                    company = company_a.get_text(strip=True)

            h3 = c.select_one("h3")
            salary = h3.get_text(strip=True) if h3 else "Не указана"

            work_format = "Можно удалённо" if "удаленн" in title.lower() else "Не указан"

            results.append({
                "source": "Remote-Job",
                "title": title, "company": company, "salary": salary,
                "city": "Удалённо", "work_format": work_format, "grade": "",
                "days_ago": days_ago, "url": url_v,
            })
        return results, None
    except Exception as e:
        return [], f"Сбой Remote-Job: {e}"

# ========== ПАРСИНГ HIRIFY ==========
def parse_hirify_date(date_text: str) -> int:
    date_text = date_text.lower().strip()
    if "секунд" in date_text or "минут" in date_text or "час" in date_text:
        return 0
    match = re.search(r'(\d+)\s*дн', date_text)
    if match:
        return int(match.group(1))
    if "недел" in date_text:
        match = re.search(r'(\d+)', date_text)
        if match:
            return int(match.group(1)) * 7
        return 7
    if re.match(r'\d{1,2}\s+\w{3}', date_text):
        return 0
    return 999

async def search_hirify(query: str):
    url = "https://hirify.me/"
    params = {"params": "title,company", "search": query}
    print(f"🔍 Hirify: {query}")
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return [], f"Hirify: статус {r.status}"
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("a.vacancy-card-link")
        print(f"🃏 Hirify карточек: {len(cards)}")

        results = []
        for c in cards:
            title_tag = c.select_one("h3.title")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)

            href = c.get("href", "")
            url_v = "https://hirify.me" + href if href.startswith("/") else href

            company_tag = c.select_one("span.blurred-company")
            company = company_tag.get_text(strip=True) if company_tag else "Скрыта"

            tags = c.select("div.tag")
            tag_texts = [t.get_text(strip=True).lower() for t in tags]

            work_format = "Не указан"
            city = "Не указан"

            for tag in tag_texts:
                if "remote" in tag:
                    work_format = "Можно удалённо"
                elif "onsite" in tag:
                    work_format = "В офисе"
                elif "hybrid" in tag:
                    work_format = "Гибрид"

                if tag not in ["remote", "onsite", "hybrid", "fulltime", "parttime", "contract"]:
                    if any(country in tag for country in ["russia", "uk", "usa", "germany", "spain", "london", "moscow"]):
                        city = tag.title()

            date_div = c.select_one("div.date-full")
            date_text = date_div.get_text(strip=True) if date_div else ""
            days_ago = parse_hirify_date(date_text)

            results.append({
                "source": "Hirify",
                "title": title, "company": company, "salary": "Не указана",
                "city": city, "work_format": work_format, "grade": "",
                "days_ago": days_ago, "url": url_v,
            })
        return results, None
    except Exception as e:
        return [], f"Сбой Hirify: {e}"

# ========== ФИЛЬТРЫ ==========
def apply_filters(items, city, fmt, days):
    out = []
    for it in items:
        if city != "any" and city.lower() not in it["city"].lower():
            continue
        if fmt == "remote" and "удалённ" not in it["work_format"].lower():
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
    if days < 0: return "только что"
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
        "Я бот поиска вакансий с <b>четырьмя источниками</b>:\n"
        "🔵 Хабр Карьера\n"
        "🟢 SuperJob\n"
        "🌐 Remote-Job (удалёнка)\n"
        "💼 Hirify (международные)\n\n"
        "Напиши, кого ищешь (например: <code>аналитик</code>),\n"
        "а я задам уточняющие вопросы.\n\n"
        "Команда /cancel — сброс.",
        parse_mode="HTML"
    )

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔄 Поиск сброшен. Напиши новый запрос.")

@router.message(SearchStates.waiting_custom_city, F.text)
async def custom_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await state.set_state(SearchStates.waiting_format)
    await message.answer("🏢 Формат работы?", reply_markup=KB_FORMAT)

@router.message(F.text)
async def start_search(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is not None:
        return
    await state.clear()
    await state.update_data(query=message.text.strip(), city="any", fmt="any", source="all")
    await state.set_state(SearchStates.waiting_source)
    await message.answer("🌐 Где ищем?", reply_markup=KB_SOURCE)

@router.callback_query(F.data.startswith("src:"))
async def cb_source(callback: CallbackQuery, state: FSMContext):
    await state.update_data(source=callback.data.split(":", 1)[1])
    await state.set_state(SearchStates.waiting_city)
    await callback.message.edit_text("📍 Выбери город:", reply_markup=KB_CITY)
    await callback.answer()

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
    await callback.message.edit_text("📅 Насколько свежие?", reply_markup=KB_FRESH)
    await callback.answer()

@router.callback_query(F.data.startswith("fresh:"))
async def cb_fresh(callback: CallbackQuery, state: FSMContext):
    days = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    src = data.get("source", "all")
    source_label = {
        "habr": "Хабр Карьера",
        "sj": "SuperJob",
        "remote": "Remote-Job",
        "hirify": "Hirify",
        "all": "Все источники"
    }[src]
    await callback.message.edit_text(f"⏳ Ищу на <b>{source_label}</b>...", parse_mode="HTML")
    await callback.answer()

    results = []
    errors = []
    if src in ("habr", "all"):
        r, e = await search_habr(data.get("query", ""))
        results.extend(r)
        if e: errors.append(e)
    if src in ("sj", "all"):
        r, e = await search_superjob(data.get("query", ""))
        results.extend(r)
        if e: errors.append(e)
    if src in ("remote", "all"):
        r, e = await search_remote_job(data.get("query", ""))
        results.extend(r)
        if e: errors.append(e)
    if src in ("hirify", "all"):
        r, e = await search_hirify(data.get("query", ""))
        results.extend(r)
        if e: errors.append(e)

    results = deduplicate_and_sort(results)
    filtered = apply_filters(results, data.get("city", "any"), data.get("fmt", "any"), days)
    filtered = filtered[:MAX_RESULTS]
    print(f"✅ После фильтров: {len(filtered)} из {len(results)}")

    if errors and not filtered:
        await callback.message.edit_text("❌ " + "\n".join(errors))
        return
    if not filtered:
        await callback.message.edit_text(
            "😕 Ничего не найдено с такими фильтрами.\n"
            "Попробуй ослабить фильтры или сменить источник."
        )
        return

    await callback.message.edit_text(f"✅ Найдено: {len(filtered)}")

    chat_id = callback.message.chat.id
    SEARCH_CACHE[chat_id] = {"items": filtered, "offset": 0}

    page = filtered[:PAGE_SIZE]
    for job in page:
        await send_vacancy(chat_id, job)
    offset = len(page)
    SEARCH_CACHE[chat_id]["offset"] = offset

    if offset < len(filtered):
        await bot.send_message(
            chat_id,
            f"📄 Показано {offset} из {len(filtered)}",
            reply_markup=more_keyboard(len(filtered) - offset)
        )

@router.callback_query(F.data == "more")
async def cb_more(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    cache = SEARCH_CACHE.get(chat_id)
    if not cache or not cache["items"]:
        await callback.answer("Нечего показывать. Начни новый поиск.", show_alert=True)
        return

    items = cache["items"]
    offset = cache["offset"]
    page = items[offset:offset + PAGE_SIZE]
    for job in page:
        await send_vacancy(chat_id, job)
    offset += len(page)
    cache["offset"] = offset

    if offset < len(items):
        await callback.message.edit_text(
            f"📄 Показано {offset} из {len(items)}",
            reply_markup=more_keyboard(len(items) - offset)
        )
    else:
        await callback.message.edit_text(f"✅ Это все вакансии: {len(items)}")
    await callback.answer()

async def main():
    print("✅ Бот запущен!")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка polling: {e}")
        if "Conflict" in str(e):
            import sys
            sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())