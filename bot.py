from flask import Flask, request
import feedparser
import requests
import json
import logging
import os
import hashlib
from datetime import datetime

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" if TELEGRAM_TOKEN else None
FEEDCACHE_FILE = "feedcache.json"

RSS_URLS = [
    "https://www.theverge.com/rss/index.xml",
    "https://www.windowscentral.com/feed",
    "https://www.windowslatest.com/feed/",
    "https://9to5google.com/feed/",
    "https://9to5mac.com/feed/",
    "https://www.androidcentral.com/feed",
    "https://arstechnica.com/feed/",
    "https://uk.pcmag.com/rss",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.androidauthority.com/news/feed/",
    "https://feeds.feedburner.com/Techcrunch"
]
current_index = 0

def send_message(chat_id, text):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан в переменных окружения")
        return
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    logger.info(f"Sending message to chat_id {chat_id}: {text[:50]}...")
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Failed to send message: {response.text}")

def send_file(chat_id, file_path):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан в переменных окружения")
        return
    
    with open(file_path, 'rb') as f:
        files = {'document': (file_path, f)}
        payload = {"chat_id": chat_id}
        response = requests.post(f"{TELEGRAM_URL}sendDocument", data=payload, files=files)
    if response.status_code != 200:
        logger.error(f"Failed to send file: {response.text}")

def get_article_content(url):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан", "Ошибка: OPENROUTER_API_KEY не задан"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Tech_Chronicle",
        "X-Title": "TChNewsBot"
    }
    data = {
        "model": "google/gemma-2-9b-it:free",
        "messages": [
            {
                "role": "user",
                "content": f"""
По ссылке {url} напиши новость на русском в следующем формате:
Заголовок в стиле новостного канала
Основная суть новости в 1-2 предложениях из статьи.

Требования:
- Бери данные только из статьи, ничего не придумывай.
- Внимательно проверяй даты и числа в статье, не путай их.
- Не добавляй "| Источник", названия сайтов или эмодзи.
- Не используй форматирование вроде ##, ** или [].
- Максимальная длина пересказа — 500 символов.
"""
            }
        ]
    }
    try:
        logger.info(f"Requesting content for URL: {url}")
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(data),
            timeout=15
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Content response: {json.dumps(result, ensure_ascii=False)}")
        
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"].strip()
            if "\n" in content:
                title, summary = content.split("\n", 1)
                return title, summary[:500]
            return content[:80], "Пересказ не получен"
        return "Ошибка: Нет ответа от API", "Ошибка: Нет ответа от API"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе")
        return "Ошибка: Таймаут", "Ошибка: Таймаут"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса: {str(e)}")
        return f"Ошибка: {str(e)}", f"Ошибка: {str(e)}"

def save_to_feedcache(title, summary, link, source):
    entry = {
        "id": hashlib.md5(link.encode()).hexdigest(),
        "title": title,
        "summary": summary,
        "link": link,
        "source": source,
        "timestamp": datetime.now().isoformat()
    }
    
    if os.path.exists(FEEDCACHE_FILE):
        with open(FEEDCACHE_FILE, 'r', encoding='utf-8') as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = []
    else:
        cache = []
    
    cache.append(entry)
    with open(FEEDCACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved to feedcache: {entry['id']}")

def post_latest_news(chat_id):
    global current_index
    attempts = 0
    max_attempts = len(RSS_URLS)
    
    while attempts < max_attempts:
        rss_url = RSS_URLS[current_index]
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            logger.warning(f"No entries found in RSS feed: {rss_url}")
            current_index = (current_index + 1) % len(RSS_URLS)
            attempts += 1
            continue
        
        latest_entry = feed.entries[0]
        link = latest_entry.link
        
        logger.info(f"Processing news from: {link} (source: {rss_url})")
        title_ru, summary_ru = get_article_content(link)
        message = f"<b>{title_ru}</b> <a href='{link}'>| Источник</a>\n{summary_ru}"
        
        send_message(CHANNEL_ID, message)
        send_message(chat_id, f"Новость отправлена в @TechChronicleTest (источник: {rss_url.split('/')[2]})")
        save_to_feedcache(title_ru, summary_ru, link, rss_url.split('/')[2])
        
        current_index = (current_index + 1) % len(RSS_URLS)
        break
    else:
        send_message(chat_id, "Не удалось найти новости в доступных RSS-лентах")
        logger.error("All RSS feeds returned empty entries")

def get_feedcache(chat...

Что-то пошло не так, повторите попытку.