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

QUERIES = ["бизнес-аналитик", "менеджер по качеству", "системный аналитик"]
MAX_PER_QUERY = 50

# ========== УТИЛИТЫ ==========
def parse_age_hours(text):
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
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())[:40]
    company_norm = company.lower().strip()[:30]
    return (title_norm, company_norm)

# ========== ПАРСИНГ GORODRABOT ==========
async def search_gorodrabot(query: str):
    encoded_query = quote(query.replace(' ', '_'))
    url = f"https://sankt-peterburg.gorodrabot.ru/{encoded_query}"
    print(f"🔍 ГородРабот: {query}")
    print(f"   URL: {url}")
    
    all_vacancies = []
    page = 1
    
    async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25)) as s:
        while page <= 3:
            params = {"page": str(page)} if page > 1 else {}
            
            # Задержка перед запросом
            if page > 1:
                print(f"   Пауза 15 секунд...")
                await asyncio.sleep(15)
            
            async with s.get(url, params=params) as r:
                print(f"   Страница {page}: статус {r.status}")
                if r.status != 200:
                    print(f"   Ошибка: статус {r.status}")
                    break
                html = await r.text()
            
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.snippet__body")
            print(f"   Найдено карточек: {len(cards)}")
            
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
                
                salary_tag = card.select_one("span.snippet__salary")
                salary = salary_tag.get_text(strip=True).replace('\n', ' ') if salary_tag else "Не указана"
                
                company_tag = card.select_one("li.snippet__meta-item_company span.snippet__meta-value")
                company = company_tag.get_text(strip=True) if company_tag else "Не указано"
                
                city_tag = card.select_one("li.snippet__meta-item_location span.snippet__meta-value")
                city = city_tag.get_text(strip=True) if city_tag else "Не указан"
                
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
    
    print(f"🃏 ГородРабот: всего {len(all_vacancies)} вакансий")
    return all_vacancies

async def search_getmatch(query: str):
    print(f"⏭️ GetMatch: пропущен (требуется Playwright)")
    return []

async def send_vacancy(chat_id, job, query):
    age_text = "сегодня" if job["age_hours"] == 0 else f"{job['age_hours']} ч. назад"
    
    text = (
        f"<i>[{job['source']}]</i>\n"
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company']}\n"
        f"💰 {job['salary']}\n"
        f"📅 {age_text}\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть вакансию", url=job["url"])]
    ])
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

async def main():
    if not BOT_TOKEN:
        print("❌ Не задан BOT2_TOKEN")
        return
    if not CHAT_ID:
        print("❌ Не задан CHAT_ID")
        return
    
    chat_id = int(CHAT_ID)
    
    print(f"📨 Дайджест Бот-2 запущен")
    
    for query in QUERIES:
        results = []
        for fn in (search_gorodrabot, search_getmatch):
            r = await fn(query)
            results.extend(r)
        
        seen = set()
        unique = []
        for v in results:
            key = make_key(v["title"], v["company"])
            if key not in seen:
                seen.add(key)
                unique.append(v)
        
        fresh = [v for v in unique if v["age_hours"] <= 24]
        
        print(f"📊 '{query}': всего {len(unique)}, свежих (≤24ч): {len(fresh)}")
        
        if not fresh:
            continue
        
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
        
        # Пауза между запросами
        print("   Пауза 15 секунд перед следующим запросом...")
        await asyncio.sleep(15)
    
    print("✅ Дайджест завершён")

if __name__ == "__main__":
    asyncio.run(main())