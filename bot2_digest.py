import asyncio
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT2_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

bot = Bot(token=BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# Telegram-каналы: (имя, режим)
#   kw_and_order — роль в заголовке И маркер заказа в первых 150 символах
#   kw_only      — роль в заголовке достаточна
TG_CHANNELS = [
    ("ba_and_sa", "kw_and_order"),
    ("data_analysis_jobs", "kw_and_order"),
    ("ipomogator", "kw_only"),
    ("distantsiya", "kw_only"),
    ("frilanser_vacansii", "kw_only"),
    ("workzavr", "kw_only"),
    ("partnerkin_job", "kw_only"),
]

# РОЛЬ ИЩЕМ ТОЛЬКО В ЗАГОЛОВКЕ (слово «качество» убрано полностью)
ROLE_IN_TITLE = [
    "аналитик", "bpmn", "бизнес-процесс", "бизнес процесс", "бизнес-анализ",
    "системный анализ", "методолог", "смк", "сертификац", "стандартизац",
    "регламент",
]

# Маркеры заказа (точное совпадение слова)
ORDER_MARKERS_RE = [
    r"\bищем\b", r"\bищу\b", r"\bтребуется\b", r"\bнужен\b", r"\bнужна\b",
    r"\bваканс\w*", r"\bзаказ\b", r"\bзаказы\b", r"\bгонорар\b", r"\bоплат\w*",
    r"\bподработ\w*", r"\bразов\w*", r"\bфриланс\w*", r"\bпроектн\w*",
    r"\bстажиров\w*", r"\bнайм\b", r"\bвозьмусь\b", r"\bготов\s+выполнить\b"
]

# Запросы для freelance.ru
FREELANCE_QUERIES = ["аналитик"]

MAX_RESULTS = 50
FRESH_HOURS = 24    # если слишком тихо — можно поставить 72 (3 суток)

# ========== УТИЛИТЫ ==========
def parse_age_hours(text):
    text = text.lower()
    if "сегодня" in text or "только что" in text or "минут" in text:
        return 0
    match = re.search(r'(\d+)\s*час', text)
    if match:
        return int(match.group(1))
    if re.search(r'(час|часа)\s+назад', text):
        return 1
    if "день назад" in text or "дня назад" in text or "вчера" in text:
        return 24
    return 999

def parse_iso_age_hours(iso_date):
    if not iso_date:
        return 999
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        return int(delta.total_seconds() // 3600)
    except Exception:
        return 999

def make_key(title, source):
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())[:50]
    return (title_norm, source)

def is_order_post(title, text, mode):
    """Роль — только в заголовке; маркер заказа — в первых 150 символах (или весь текст для kw_only не нужен)."""
    low_title = title.lower()
    has_role = any(k in low_title for k in ROLE_IN_TITLE)
    if not has_role:
        return False
    if mode == "kw_only":
        return True
    head = text[:150].lower()
    return any(re.search(m, head) for m in ORDER_MARKERS_RE)

# ========== ПАРСИНГ TELEGRAM ==========
async def parse_telegram_channel(session, channel_name, mode):
    url = f"https://t.me/s/{channel_name}"
    tasks = []

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                print(f"   @{channel_name}: статус {r.status}")
                return []
            html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        posts = soup.select("div.tgme_widget_message")

        for post in posts:
            text_div = post.select_one("div.tgme_widget_message_text")
            if not text_div:
                continue

            text = text_div.get_text(" ", strip=True)
            title = text[:100].strip()
            if len(text) > 100:
                title += "..."

            if not is_order_post(title, text, mode):
                continue

            time_tag = post.find("time")
            date_str = time_tag.get("datetime", "") if time_tag else ""
            age = parse_iso_age_hours(date_str)

            link_tag = post.select_one("a.tgme_widget_message_date")
            post_url = link_tag.get("href", "") if link_tag else f"https://t.me/{channel_name}"

            print(f"      • [{age} ч назад] {title[:60]}")

            tasks.append({
                "source": f"TG @{channel_name}",
                "title": title,
                "description": text[:300],
                "price": "Не указана",
                "date_str": date_str,
                "url": post_url,
                "age_hours": age,
            })

        print(f"   @{channel_name}: найдено {len(tasks)} подходящих заказов")

    except Exception as e:
        print(f"   @{channel_name}: ошибка {type(e).__name__}")

    return tasks

# ========== ПАРСИНГ FREELANCE.RU ==========
async def parse_freelance_ru(session, query):
    url = f"https://freelance.ru/task?q={quote(query)}"
    tasks = []

    print(f"   freelance.ru: запрос '{query}'")

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                print(f"      статус {r.status}")
                return []
            html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n")

        blocks = text.split("Видно всем")[1:]
        print(f"      блоков карточек: {len(blocks)}")

        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            title = lines[0]

            date_str = ""
            date_idx = None
            for i, l in enumerate(lines):
                if re.search(r'(только что|\d+\s*минут\w*|минуту|\d+\s*час\w*|час\s+назад|день\s+назад|дня\s+назад|дней\s+назад|вчера)', l):
                    date_str = l
                    date_idx = i
                    break
            if date_idx is None:
                continue

            price = "Не указана"
            for i, l in enumerate(lines):
                if l.startswith("Гонорар") and i + 1 < len(lines):
                    price = lines[i + 1]
                    break

            description = " ".join(lines[1:date_idx])[:300]

            if not is_order_post(title, title + " " + description, "kw_only"):
                continue

            age = parse_age_hours(date_str)

            print(f"      • [{age} ч назад] {title[:60]} | {price}")

            tasks.append({
                "source": "freelance.ru",
                "title": title[:100],
                "description": description,
                "price": price,
                "date_str": date_str,
                "url": url,
                "age_hours": age,
            })

        print(f"      найдено {len(tasks)} заданий")

    except Exception as e:
        print(f"      ошибка {type(e).__name__}: {e}")

    return tasks

# ========== ОТПРАВКА ЗАДАНИЙ ==========
async def send_task(chat_id, task):
    age_text = "сегодня" if task["age_hours"] <= 1 else f"{task['age_hours']} ч. назад"

    text = (
        f"<i>[{task['source']}]</i>\n"
        f"💼 <b>{task['title']}</b>\n"
        f"💰 {task['price']}\n"
        f"📅 {age_text}\n\n"
        f"{task['description']}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть задание", url=task["url"])]
    ])
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

# ========== ОСНОВНАЯ ЛОГИКА ==========
async def main():
    if not BOT_TOKEN:
        print("❌ Не задан BOT2_TOKEN")
        return
    if not CHAT_ID:
        print("❌ Не задан CHAT_ID")
        return

    chat_id = int(CHAT_ID)

    print(f"📨 Дайджест подработок запущен")

    all_tasks = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for channel, mode in TG_CHANNELS:
            tasks = await parse_telegram_channel(session, channel, mode)
            all_tasks.extend(tasks)
            await asyncio.sleep(2)

        for query in FREELANCE_QUERIES:
            tasks = await parse_freelance_ru(session, query)
            all_tasks.extend(tasks)
            await asyncio.sleep(2)

    best = {}
    for task in all_tasks:
        key = make_key(task["title"], task["source"])
        if key not in best or task["age_hours"] < best[key]["age_hours"]:
            best[key] = task
    unique = list(best.values())

    fresh = [t for t in unique if t["age_hours"] <= FRESH_HOURS]
    fresh.sort(key=lambda x: x["age_hours"])

    print(f"📊 Всего: {len(unique)}, свежих (≤{FRESH_HOURS}ч): {len(fresh)}")

    if not fresh:
        print("😴 Свежих заданий не найдено")
        return

    await bot.send_message(
        chat_id,
        f"🔍 <b>Подработка и разовые заказы</b>\n"
        f"📅 Свежесть: {FRESH_HOURS} часа\n"
        f"✅ Найдено: {len(fresh)}",
        parse_mode="HTML"
    )

    for task in fresh[:MAX_RESULTS]:
        await send_task(chat_id, task)
        await asyncio.sleep(0.5)

    print("✅ Дайджест завершён")

if __name__ == "__main__":
    asyncio.run(main())