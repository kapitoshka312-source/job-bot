import asyncio
import aiohttp
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

CHANNELS = ["bpmn2ru", "analyst_job", "ipomogator"]

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        print("=== Telegram с GitHub ===")
        for ch in CHANNELS:
            try:
                async with s.get(f"https://t.me/s/{ch}", timeout=aiohttp.ClientTimeout(total=20)) as r:
                    html = await r.text()
                    soup = BeautifulSoup(html, "html.parser")
                    posts = soup.select("div.tgme_widget_message")
                    print(f"  @{ch}: статус {r.status}, постов {len(posts)}")
            except Exception as e:
                print(f"  @{ch}: {type(e).__name__}: {e}")

asyncio.run(main())
