#!/usr/bin/env python3
"""
AI News Notifier
-----------------
ดึงข่าว/บทความความรู้จาก RSS -> ให้ Claude สรุปเป็นภาษาไทยแบบกระชับ -> ส่งแจ้งเตือนเข้า Telegram

วิธีใช้งาน:
1. ติดตั้งไลบรารีที่ต้องใช้:
     pip install feedparser requests

2. ตั้งค่า Environment Variables (ดูวิธีขอ token ด้านล่างของไฟล์นี้):
     export TELEGRAM_BOT_TOKEN="123456:ABC-your-bot-token"
     export TELEGRAM_CHAT_ID="123456789"
     export ANTHROPIC_API_KEY="sk-ant-..."

3. รันสคริปต์:
     python3 news_notifier.py

4. ตั้งให้รันอัตโนมัติทุกวัน (เช่น 08:00) ด้วย cron:
     crontab -e
     แล้วเพิ่มบรรทัด:
     0 8 * * * /usr/bin/python3 /path/to/news_notifier.py >> /path/to/news_notifier.log 2>&1
"""

import os
import feedparser
import requests
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 1) ตั้งค่าหัวข้อ/แหล่งข่าวที่สนใจ (แก้ไข list นี้ได้ตามใจชอบ)
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "เทคโนโลยี": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "วิทยาศาสตร์": "https://www.sciencedaily.com/rss/top/science.xml",
    "AI": "https://www.artificialintelligence-news.com/feed/",
    # เพิ่มแหล่งอื่นได้ เช่นข่าวไทย, ข่าวธุรกิจ ฯลฯ
}

# ดึงเฉพาะข่าวที่โพสต์ภายในกี่ชั่วโมงล่าสุด
HOURS_LOOKBACK = 24
# จำนวนข่าวสูงสุดต่อหมวดที่จะส่ง
MAX_ITEMS_PER_FEED = 3

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------
# 2) ดึงข่าวจาก RSS
# ---------------------------------------------------------------------------
def fetch_recent_entries():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    results = []

    for category, url in RSS_FEEDS.items():
        feed = feedparser.parse(url)
        count = 0
        for entry in feed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            if count >= MAX_ITEMS_PER_FEED:
                break
            results.append({
                "category": category,
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:500],
                "link": entry.get("link", ""),
            })
            count += 1
    return results


# ---------------------------------------------------------------------------
# 3) ให้ Claude สรุปเป็นภาษาไทย กระชับ อ่านง่าย
# ---------------------------------------------------------------------------
def summarize_with_claude(entries):
    if not entries:
        return "วันนี้ไม่มีข่าวใหม่ในหมวดที่ติดตามครับ"

    if not ANTHROPIC_API_KEY:
        # ถ้าไม่ได้ตั้งค่า API key ไว้ ให้ส่งหัวข้อดิบๆ แทน
        lines = []
        for e in entries:
            lines.append(f"[{e['category']}] {e['title']}\n{e['link']}")
        return "\n\n".join(lines)

    raw_text = "\n\n".join(
        f"หมวด: {e['category']}\nหัวข้อ: {e['title']}\nเนื้อหาย่อ: {e['summary']}\nลิงก์: {e['link']}"
        for e in entries
    )

    prompt = (
        "ต่อไปนี้คือข่าว/บทความที่ดึงมาจาก RSS หลายแหล่ง ช่วยสรุปให้เป็นภาษาไทย "
        "สั้น กระชับ อ่านง่าย จัดกลุ่มตามหมวดหมู่ แต่ละข่าวสรุป 1-2 ประโยค "
        "แล้วแปะลิงก์ต้นฉบับต่อท้าย ห้ามใส่คำนำหรือสรุปปิดท้าย ตอบเนื้อหาล้วนๆ:\n\n"
        f"{raw_text}"
    )

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


# ---------------------------------------------------------------------------
# 4) ส่งข้อความเข้า Telegram
# ---------------------------------------------------------------------------
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ไม่ได้ตั้งค่า TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — พิมพ์ผลลัพธ์แทนการส่ง:\n")
        print(text)
        return

    # Telegram จำกัดความยาวข้อความ ~4096 ตัวอักษรต่อ 1 ครั้ง
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [""]

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        })
        if resp.status_code != 200:
            print("ส่งข้อความไม่สำเร็จ:", resp.text)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    today = datetime.now().strftime("%d/%m/%Y")
    entries = fetch_recent_entries()
    summary = summarize_with_claude(entries)
    message = f"📰 สรุปข่าว/ความรู้ประจำวันที่ {today}\n\n{summary}"
    send_telegram_message(message)
    print("เสร็จสิ้น ส่งข่าวไปแล้ว", len(entries), "รายการ")


if __name__ == "__main__":
    main()
