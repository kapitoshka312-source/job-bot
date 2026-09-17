import asyncio
import aiohttp
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

async def fetch(session, url):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
        return r.status, await r.text()

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as s:

        # ---------- FREELANCE.RU ----------
        print("=" * 60)
        print("FREELANCE.RU: структура карточек")
        url = "https://freelance.ru/task?keywords=%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D1%82%D0%B8%D0%BA"
        st, html = await fetch(s, url)
        print(f"статус: {st}, длина: {len(html)}")
        soup = BeautifulSoup(html, "html.parser")
        
        # ищем карточки
        for tag in ["div", "article", "li"]:
            cards = [c for c in soup.find_all(tag, class_=True) 
                     if any(k in " ".join(c.get("class", [])) for k in ["task", "order", "project", "item", "card"])]
            if cards:
                print(f"  <{tag}> с классом task/order/project/item/card: {len(cards)}")
                if cards:
                    print(f"  --- первая карточка ---")
                    print(cards[0].prettify()[:1500])
                    break
        else:
            print("  карточек не найдено, первый 1000 символов HTML:")
            print(html[:1000])

        # ---------- KWORK ----------
        print("=" * 60)
        print("KWORK: структура карточек")
        url = "https://kwork.ru/search?search=аналитик"
        st, html = await fetch(s, url)
        print(f"статус: {st}, длина: {len(html)}")
        soup = BeautifulSoup(html, "html.parser")
        
        for tag in ["div", "article", "li"]:
            cards = [c for c in soup.find_all(tag, class_=True) 
                     if any(k in " ".join(c.get("class", [])) for k in ["kwork", "card", "item", "product"])]
            if cards:
                print(f"  <{tag}> с классом kwork/card/item/product: {len(cards)}")
                if cards:
                    print(f"  --- первая карточка ---")
                    print(cards[0].prettify()[:1500])
                    break
        else:
            print("  карточек не найдено, первые 1000 символов HTML:")
            print(html[:1000])

asyncio.run(main())