import asyncio
import os
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8934279737:AAElBwd3DS1dsZFoZx9ZhpzlaHpuu4Ksa7g")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

async def search_hh(query: str, limit: int = 3):
    url = "https://api.hh.ru/vacancies"
    params = {"text": query, "per_page": limit}
    headers = {"User-Agent": "JobSearchBot/1.0 (test@test.com)"}
    
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for v in data.get('items', []):
                        salary = "Не указана"
                        if v.get("salary"):
                            s = v["salary"]
                            fr = s.get("from", "")
                            to = s.get("to", "")
                            cur = s.get("currency", "₽")
                            if fr and to: salary = f"{fr} - {to} {cur}"
                            elif fr: salary = f"от {fr} {cur}"
                            elif to: salary = f"до {to} {cur}"
                        
                        results.append({
                            "title": v.get("name", "Не указано"),
                            "company": v.get("employer", {}).get("name", "Не указано"),
                            "salary": salary,
                            "city": v.get("area", {}).get("name", "Не указан"),
                            "url": v.get("alternate_url", "")
                        })
                    return results, None
                else:
                    return [], f"Ошибка hh.ru: статус {resp.status}"
    except Exception as e:
        return [], f"Сбой соединения: {str(e)}"

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
    
    results, error = await search_hh(query, limit=3)
    
    if error:
        await status_msg.edit_text(
            f"❌ Произошла ошибка при поиске:\n\n"
            f"<code>{error}</code>", 
            parse_mode="HTML"
        )
        return
    
    if not results:
        await status_msg.edit_text("😕 Ничего не найдено. Попробуй другой запрос.")
        return
    
    await status_msg.edit_text(f"✅ Готово! Найдено вакансий: {len(results)}")
    
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
    print("✅ Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())