import asyncio
import os
from datetime import datetime, timezone, timedelta

from bot1 import (
    bot,
    search_habr, search_superjob, search_remote_job, search_hirify,
    deduplicate_and_sort, send_vacancy,
)

# Расписание рассылок (время МОСКОВСКОЕ): час -> запрос
SCHEDULE = {
    10: "бизнес-аналитик",
    11: "системный аналитик",
    12: "специалист по бизнес-процессам",
    14: "менеджер по качеству",
    15: "специалист по сертификации",
    16: "менеджер по СМК",
    17: "методолог",
}

CHAT_ID = os.getenv("CHAT_ID", "")
MAX_PER_DIGEST = 20  # максимум вакансий в одной рассылке

async def main():
    if not CHAT_ID:
        print("❌ Не задан CHAT_ID")
        return
    chat_id = int(CHAT_ID)

    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    test_hour = os.getenv("TEST_HOUR", "").strip()
    hour = int(test_hour) if test_hour.isdigit() else msk.hour

    query = SCHEDULE.get(hour)
    if not query:
        print(f"⏭️ Сейчас {msk:%H:%M} МСК (час={hour}) — не время рассылки, выходим")
        return

    print(f"📨 Дайджест {hour}:00 МСК | запрос: «{query}»")
    await bot.send_message(
        chat_id,
        f"⏰ Дайджест {hour}:00 МСК\n🔍 Запрос: «{query}»\n📅 Вакансии за последние 24 часа, все источники"
    )

    results = []
    for fn in (search_habr, search_superjob, search_remote_job, search_hirify):
        r, err = await fn(query)
        if err:
            print("⚠️", err)
        results.extend(r)

    results = deduplicate_and_sort(results)
    fresh = [v for v in results if v.get("days_ago", 999) <= 1]
    print(f"📊 Всего: {len(results)}, свежих (<=24ч): {len(fresh)}")

    if not fresh:
        await bot.send_message(chat_id, "😴 За последние 24 часа новых вакансий не появилось.")
        return

    for job in fresh[:MAX_PER_DIGEST]:
        await send_vacancy(chat_id, job)

    if len(fresh) <= MAX_PER_DIGEST:
        await bot.send_message(chat_id, f"✅ Дайджест завершён: {len(fresh)} свежих вакансий")
    else:
        await bot.send_message(chat_id, f"✅ Дайджест завершён: {len(fresh)} свежих, показаны первые {MAX_PER_DIGEST}")

asyncio.run(main())