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

# Telegram-каналы для парсинга
TG_CHANNELS = [
    "bpmn2ru",           # BPM, бизнес-процессы
    "analyst_job",       # Работа для системных и бизнес-аналитиков
    "ba_and_sa",         # Бизнес и системные аналитики
    "ipomogator",        # Биржа фриланса
    "distantsiya",       # Удалённая работа и фриланс
]

# Ключевые слова для фильтрации
KEYWORDS = [
    "аналитик", "bpmn", "бизнес-процесс", "смк", "качеств",
    "методолог", "подработк", "разов", "проект", "фриланс",
    "регламент", "процесс", "требован", "документаци"
]

MAX_RESULTS = 50

# ========== УТИЛИТЫ ==========
def parse_age_hours(text):
    """Парсит возраст из текста типа '44 минуты назад', '5 часов назад', 'день назад'."""
    text = text.lower()
    if "сегодня" in text or "минут" in text:
        return 0
    match = re.search(r'(\d+)\s*час', text)
    if match:
        return int(match.group(1))
    if "день назад" in text or "дня назад" in text:
        return 24
    if "вчера" in text:
        return 24
    return 999

def make_key(title, source):
    """Ключ для дедупликации."""
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())[:50]
    return (title_norm, source)

def matches_keywords(text):
    """Проверяет, есть ли ключевые слова в тексте."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)

# ========== ПАРСИНГ TELEGRAM ==========
async def parse_telegram_channel(session, channel_name):
    """Парсит посты из Telegram-канала через t.me/s/"""
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
            
            if not matches_keywords(text):
                continue
            
            time_tag = post.select_one("time.datetime")
            date_str = time_tag.get("datetime", "") if time_tag else ""
            
            post_url = f"https://t.me/{channel_name}"
            
            title = text[:100].strip()
            if len(text) > 100:
                title += "..."
            
            tasks.append({
                "source": f"TG @{channel_name}",
                "title": title,
                "description": text[:300],
                "price": "Не указана",
                "date_str": date_str,
                "url": post_url,
                "age_hours": parse_age_hours(date_str) if date_str else 999,
            })
        
        print(f"   @{channel_name}: найдено {len(tasks)} подходящих заданий")
        
    except Exception as e:
        print(f"   @{channel_name}: ошибка {type(e).__name__}")
    
    return tasks

# ========== ПАРСИНГ FREELANCE.RU ==========
async def parse_freelance_ru(session):
    """Парсит задания с freelance.ru"""
    url = "https://freelance.ru/task"
    tasks = []
    
    print(f"   freelance.ru: загрузка ленты заданий")
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                print(f"   freelance.ru: статус {r.status}")
                return []
            html = await r.text()
        
        soup = BeautifulSoup(html, "html.parser")
        
        all_divs = soup.find_all("div")
        
        for div in all_divs:
            text = div.get_text(" ", strip=True)
            
            if "Видно всем" not in text:
                continue
            if "Гонорар" not in text:
                continue
            
            if not matches_keywords(text):
                continue
            
            lines = text.split("\n")
            title = ""
            description = ""
            price = "Не указана"
            date_str = ""
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                if not title and len(line) > 20 and "Видно всем" not in line:
                    title = line
                    continue
                
                if "Гонорар" in line:
                    price_match = re.search(r'([\d\s]+₽/ заказ|Обсуждается индивидуально)', line)
                    if price_match:
                        price = price_match.group(1).strip()
                    continue
                
                date_match = re.search(r'(\d+ минут|минуту|часа?|часов|день|дня|дней) назад', line)
                if date_match:
                    date_str = date_match.group(0)
                    continue
                
                if title and "Гонорар" not in line and len(line) > 30:
                    description += " " + line
            
            if title:
                tasks.append({
                    "source": "freelance.ru",
                    "title": title[:100],
                    "description": description[:300].strip(),
                    "price": price,
                    "date_str": date_str,
                    "url": "https://freelance.ru/task",
                    "age_hours": parse_age_hours(date_str),
                })
        
        print(f"   freelance.ru: найдено {len(tasks)} подходящих заданий")
        
    except Exception as e:
        print(f"   freelance.ru: ошибка {type(e).__name__}: {e}")
    
    return tasks

# ========== ОТПРАВКА ЗАДАНИЙ ==========
async def send_task(chat_id, task):
    """Отправляет одно задание."""
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
        for channel in TG_CHANNELS:
            tasks = await parse_telegram_channel(session, channel)
            all_tasks.extend(tasks)
            await asyncio.sleep(2)
        
        freelance_tasks = await parse_freelance_ru(session)
        all_tasks.extend(freelance_tasks)
    
    seen = set()
    unique = []
    for task in all_tasks:
        key = make_key(task["title"], task["source"])
        if key not in seen:
            seen.add(key)
            unique.append(task)
    
    fresh = [t for t in unique if t["age_hours"] <= 24]
    
    print(f"📊 Всего: {len(unique)}, свежих (≤24ч): {len(fresh)}")
    
    if not fresh:
        print("😴 Свежих заданий не найдено")
        return
    
    await bot.send_message(
        chat_id,
        f"🔍 <b>Подработка и разовые заказы</b>\n"
        f"📅 Свежесть: 24 часа\n"
        f"✅ Найдено: {len(fresh)}",
        parse_mode="HTML"
    )
    
    fresh.sort(key=lambda x: x["age_hours"])
    
    for task in fresh[:MAX_RESULTS]:
        await send_task(chat_id, task)
        await asyncio.sleep(0.5)
    
    print("✅ Дайджест завершён")

if __name__ == "__main__":
    asyncio.run(main())