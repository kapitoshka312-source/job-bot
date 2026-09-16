import asyncio
import os
import re
from datetime import datetime, timezone, timedelta
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT2_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

bot = Bot(token=BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

QUERIES = ["бизнес-аналитик", "менеджер по качеству", "системный аналитик"]
MAX_PER_QUERY = 50

# ========== УТИЛИТЫ ==========
def parse_age_hours(text):
    """Парсит возраст вакансии из текста типа '7 часов назад', 'сегодня'."""
    text = text.lower()
    if "сегодня" in text:
        return 0
    match = re.search(r'(\d+)\s*час', text)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s*мин', text)
    if match:
        return 0
    return 999

def make_key(title, company):
    """Ключ для дедупликации."""
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())[:40]
    company_norm = company.lower().strip()[:30]
    return (title_norm, company_norm)

# ========== ПАРСИНГ GORODRABOT ==========
async def search_gorodrabot(query: str):
    """Парсит ГородРабот для Санкт-Петербурга."""
    from urllib.parse import quote
    encoded_query = quote(query.replace(' ', '_'))
    url = f"https://sankt-peterburg.gorodrabot.ru/{encoded_query}"
    print(f"🔍 ГородРабот: {query}")
    
    all_vacancies = []
    page = 1
    
    async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25)) as s:
        while page <= 5:  # максимум 5 страниц
            params = {"page": str(page)} if page > 1 else {}
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    break
                html = await r.text()
            
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.snippet__body")
            
            if not cards:
                break
            
            for card in cards:
                title_tag = card.select_one("h2.snippet__title a")
                if not title_tag:
                    continue
                
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://gorodrabot.ru" + href
                
                # Зарплата
                salary_tag = card.select_one("span.snippet__salary")
                salary = salary_tag.get_text(strip=True).replace('\n', ' ') if salary_tag else "Не указана"
                
                # Компания
                company_tag = card.select_one("li.snippet__meta-item_company span.snippet__meta-value")
                company = company_tag.get_text(strip=True) if company_tag else "Не указано"
                
                # Город
                city_tag = card.select_one("li.snippet__meta-item_location span.snippet__meta-value")
                city = city_tag.get_text(strip=True) if city_tag else "Не указан"
                
                # Возраст (ищем в родительском div)
                parent = card.find_parent("div", class_="snippet__inner") or card
                age_text = parent.get_text(" ", strip=True)
                age_hours = parse_age_hours(age_text)
                
                all_vacancies.append({
                    "source": "ГородРабот",
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "city": city,
                    "age_hours": age_hours,
                    "url": href,
                })
            
            page += 1
    
    print(f"🃏 ГородРабот: найдено {len(all_vacancies)} карточек")
    return all_vacancies

# ========== ПАРСИНГ GETMATCH (ЗАГЛУШКА) ==========
async def search_getmatch(query: str):
    """GetMatch — SPA, пока не парсим."""
    print(f"⏭️ GetMatch: пропущен (требуется Playwright)")
    return []

# ========== ОСНОВНАЯ ЛОГИКА ==========
async def send_vacancy(chat_id, job, query):
    """Отправляет одну вакансию."""
    age_text = "сегодня" if job["age_hours"] == 0 else f"{job['age_hours']} ч. назад"
    
    text = (
        f"<i>[{job['source']}]</i>\n"
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company']}\n"
        f"💰 {job['salary']}\n"
        f"📅 {age_text}\n"
    )
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть вакансию", url=job["url"])]
    ])
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

async def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Не задан BOT2_TOKEN или CHAT_ID")
        return
    
    chat_id = int(CHAT_ID)
    
    print(f"📨 Дайджест Бот-2 запущен")
    
    for query in QUERIES:
        results = []
        for fn in (search_gorodrabot, search_getmatch):
            r = await fn(query)
            results.extend(r)
        
        # Дедупликация
        seen = set()
        unique = []
        for v in results:
            key = make_key(v["title"], v["company"])
            if key not in seen:
                seen.add(key)
                unique.append(v)
        
        # Фильтр: только свежие (≤24 часа)
        fresh = [v for v in unique if v["age_hours"] <= 24]
        
        print(f"📊 '{query}': всего {len(unique)}, свежих (≤24ч): {len(fresh)}")
        
        if not fresh:
            continue  # молчим, если ничего не найдено
        
        # Отправляем блок
        await bot.send_message(
            chat_id,
            f"🔎 <b>{query.title()}</b>\n"
            f"📅 Свежесть: 24 часа\n"
            f"📍 Город: Санкт-Петербург\n"
            f"✅ Найдено: {len(fresh)}",
            parse_mode="HTML"
        )
        
        for job in fresh[:MAX_PER_QUERY]:
            await send_vacancy(chat_id, job, query)
    
    print("✅ Дайджест завершён")

if __name__ == "__main__":
    asyncio.run(main())