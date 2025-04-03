from flask import Flask, request
import feedparser
import requests
import json
import logging
import os
import hashlib
from datetime import datetime, timedelta

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

def send_scheduled_message(chat_id, text, schedule_date):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return False
    payload = {
        "chat_id": chat_id,
        "sender_chat_id": chat_id,  # Отправляем от имени канала
        "text": text,
        "parse_mode": "HTML",
        "schedule_date": int(schedule_date.timestamp())
    }
    logger.info(f"Планируем пост на {schedule_date} (timestamp: {int(schedule_date.timestamp())})")
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Ошибка планирования: {response.text}")
        return False
    result = response.json()
    if result.get("ok"):
        logger.info(f"Пост успешно запланирован: {json.dumps(result, ensure_ascii=False)}")
        return True
    logger.error(f"Ошибка от Telegram: {result}")
    return False

def send_message(chat_id, text):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Ошибка отправки: {response.text}")

def send_file(chat_id, file_path):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return
    with open(file_path, 'rb') as f:
        files = {'document': (file_path, f)}
        payload = {"chat_id": chat_id}
        response = requests.post(f"{TELEGRAM_URL}sendDocument", data=payload, files=files)
    if response.status_code != 200:
        logger.error(f"Ошибка отправки файла: {response.text}")

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
        "messages": [{"role": "user", "content": f"""
По ссылке {url} напиши новость на русском в следующем формате:
Заголовок в стиле новостного канала
Основная суть новости в 1-2 предложениях из статьи.

Требования:
- Бери данные только из статьи, ничего не придумывай.
- Внимательно проверяй даты и числа в статье, не путай их.
- Не добавляй "| Источник", названия сайтов или эмодзи.
- Не используй форматирование вроде ##, ** или [].
- Максимальная длина пересказа — 500 символов.
"""}]
    }
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(data), timeout=15)
        response.raise_for_status()
        result = response.json()
        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"].strip()
            if "\n" in content:
                title, summary = content.split("\n", 1)
                return title, summary[:500]
            return content[:80], "Пересказ не получен"
        return "Ошибка: Нет ответа от API", "Ошибка: Нет ответа от API"
    except Exception as e:
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
    cache = []
    if os.path.exists(FEEDCACHE_FILE):
        with open(FEEDCACHE_FILE, 'r', encoding='utf-8') as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = []
    cache.append(entry)
    with open(FEEDCACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    logger.info(f"Сохранено в feedcache: {entry['id']}")

def fetch_news(chat_id):
    start_time = datetime.now() + timedelta(minutes=5)  # Начинаем через 5 минут
    interval = timedelta(hours=1)  # Интервал 1 час
    successful = 0
    
    for i, rss_url in enumerate(RSS_URLS):
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            logger.warning(f"Нет записей в {rss_url}")
            continue
        
        latest_entry = feed.entries[0]
        link = latest_entry.link
        title, summary = get_article_content(link)
        message = f"<b>{title}</b> <a href='{link}'>| Источник</a>\n{summary}"
        
        schedule_date = start_time + (i * interval)
        if send_scheduled_message(CHANNEL_ID, message, schedule_date):
            save_to_feedcache(title, summary, link, rss_url.split('/')[2])
            successful += 1
        else:
            send_message(chat_id, f"Ошибка планирования поста для {rss_url.split('/')[2]}")
    
    send_message(chat_id, f"Запланировано {successful} постов с интервалом 1 час")

def post_latest_news(chat_id):
    global current_index
    rss_url = RSS_URLS[current_index]
    feed = feedparser.parse(rss_url)
    
    if not feed.entries:
        logger.warning(f"Нет записей в {rss_url}")
        send_message(chat_id, f"Нет новостей в {rss_url}")
        current_index = (current_index + 1) % len(RSS_URLS)
        return
    
    latest_entry = feed.entries[0]
    link = latest_entry.link
    title, summary = get_article_content(link)
    message = f"<b>{title}</b> <a href='{link}'>| Источник</a>\n{summary}"
    
    send_message(CHANNEL_ID, message)
    save_to_feedcache(title, summary, link, rss_url.split('/')[2])
    send_message(chat_id, f"Новость отправлена (источник: {rss_url.split('/')[2]})")
    
    current_index = (current_index + 1) % len(RSS_URLS)

def get_feedcache(chat_id):
    if not os.path.exists(FEEDCACHE_FILE):
        send_message(chat_id, "Feedcache пуст")
        return
    with open(FEEDCACHE_FILE, 'r', encoding='utf-8') as f:
        cache = json.load(f)
        if len(str(cache)) < 4000:
            send_message(chat_id, "Содержимое feedcache:\n" + json.dumps(cache, ensure_ascii=False, indent=2))
        else:
            send_file(chat_id, FEEDCACHE_FILE)

def clear_feedcache(chat_id):
    if os.path.exists(FEEDCACHE_FILE):
        os.remove(FEEDCACHE_FILE)
        send_message(chat_id, "Feedcache очищен")
    else:
        send_message(chat_id, "Feedcache пуст")

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if 'message' not in update or 'message_id' not in update['message']:
        return "OK", 200
    chat_id = update['message']['chat']['id']
    message_text = update['message'].get('text', '')

    if message_text == '/fetch':
        fetch_news(chat_id)
    elif message_text == '/test':
        post_latest_news(chat_id)
    elif message_text == '/feedcache':
        get_feedcache(chat_id)
    elif message_text == '/feedcacheclear':
        clear_feedcache(chat_id)
    
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)