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
PENDING_POSTS = {}  # Временное хранилище для постов на утверждение: {chat_id: {post_id: {...}}}

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

def send_message(chat_id, text, reply_markup=None):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return False
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Ошибка отправки: {response.text}")
        return False
    return True

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

def check_duplicate(link):
    if not os.path.exists(FEEDCACHE_FILE):
        return False
    with open(FEEDCACHE_FILE, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    link_hash = hashlib.md5(link.encode()).hexdigest()
    return any(entry["id"] == link_hash for entry in cache)

def fetch_news(chat_id):
    posts = []
    for rss_url in RSS_URLS:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            logger.warning(f"Нет записей в {rss_url}")
            continue
        
        latest_entry = feed.entries[0]
        link = latest_entry.link
        if check_duplicate(link):
            logger.info(f"Дубль пропущен: {link}")
            continue
        
        title, summary = get_article_content(link)
        message = f"<b>{title}</b> <a href='{link}'>| Источник</a>\n{summary}"
        posts.append({"text": message, "link": link, "source": rss_url.split('/')[2], "title": title, "summary": summary})
        if len(posts) >= 2:  # Ограничиваем 2 постами
            break
    
    if not posts:
        send_message(chat_id, "Нет новых новостей для обработки")
        return
    
    PENDING_POSTS[chat_id] = {}
    for i, post in enumerate(posts):
        post_id = f"{chat_id}_{i}"
        PENDING_POSTS[chat_id][post_id] = post
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Одобрить", "callback_data": f"approve_{post_id}"},
                    {"text": "Редактировать", "callback_data": f"edit_{post_id}"},
                    {"text": "Отклонить", "callback_data": f"reject_{post_id}"}
                ]
            ]
        }
        send_message(chat_id, post["text"], reply_markup)
    
    send_message(chat_id, "Оцени предложенные посты выше")

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
    if check_duplicate(link):
        send_message(chat_id, "Новость уже публиковалась")
        current_index = (current_index + 1) % len(RSS_URLS)
        return
    
    title, summary = get_article_content(link)
    message = f"<b>{title}</b> <a href='{link}'>| Источник</a>\n{summary}"
    
    send_message(CHANNEL_ID, message)
    save_to_feedcache(title, summary, link, rss_url.split('/')[2])
    send_message(chat_id, f"Новость отправлена (источник: {rss_url.split('/')[2]})")
    
    current_index = (current_index + 1) % len(RSS_URLS)

def handle_callback(chat_id, callback_data, message_id):
    action, post_id = callback_data.split("_", 1)
    
    if chat_id not in PENDING_POSTS or post_id not in PENDING_POSTS[chat_id]:
        send_message(chat_id, "Пост не найден")
        return
    
    post = PENDING_POSTS[chat_id][post_id]
    
    if action == "approve":
        send_message(CHANNEL_ID, post["text"])
        save_to_feedcache(post["title"], post["summary"], post["link"], post["source"])
        send_message(chat_id, "Пост одобрен и опубликован")
        del PENDING_POSTS[chat_id][post_id]
    elif action == "reject":
        send_message(chat_id, "Пост отклонён")
        del PENDING_POSTS[chat_id][post_id]
    elif action == "edit":
        send_message(chat_id, "Введите новый заголовок (оставьте пустым, если без изменений):")
        PENDING_POSTS[chat_id][post_id]["state"] = "awaiting_title"

    if not PENDING_POSTS[chat_id]:
        del PENDING_POSTS[chat_id]

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if 'message' in update and 'message_id' in update['message']:
        chat_id = update['message']['chat']['id']
        message_text = update['message'].get('text', '')
        
        if message_text == '/fetch':
            fetch_news(chat_id)
        elif message_text == '/test':
            post_latest_news(chat_id)
        elif chat_id in PENDING_POSTS:
            for post_id, post in PENDING_POSTS[chat_id].items():
                if "state" in post:
                    if post["state"] == "awaiting_title":
                        new_title = message_text.strip() or post["title"]
                        post["title"] = new_title
                        post["text"] = f"<b>{new_title}</b> <a href='{post['link']}'>| Источник</a>\n{post['summary']}"
                        send_message(chat_id, "Введите новое содержание (оставьте пустым, если без изменений):")
                        post["state"] = "awaiting_summary"
                    elif post["state"] == "awaiting_summary":
                        new_summary = message_text.strip() or post["summary"]
                        post["summary"] = new_summary
                        post["text"] = f"<b>{post['title']}</b> <a href='{post['link']}'>| Источник</a>\n{new_summary}"
                        send_message(chat_id, post["text"], {
                            "inline_keyboard": [
                                [
                                    {"text": "Одобрить", "callback_data": f"approve_{post_id}"},
                                    {"text": "Редактировать", "callback_data": f"edit_{post_id}"},
                                    {"text": "Отклонить", "callback_data": f"reject_{post_id}"}
                                ]
                            ]
                        })
                        del post["state"]
    
    elif 'callback_query' in update:
        callback = update['callback_query']
        chat_id = callback['message']['chat']['id']
        callback_data = callback['data']
        message_id = callback['message']['message_id']
        handle_callback(chat_id, callback_data, message_id)
        requests.post(f"{TELEGRAM_URL}answerCallbackQuery", json={"callback_query_id": callback['id']})
    
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)