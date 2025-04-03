from flask import Flask, request
import feedparser
import requests
import json
import logging
import os
import hashlib
import sqlite3
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" if TELEGRAM_TOKEN else None
DB_FILE = "feedcache.db"

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

# Глобальные переменные для управления постингом и статуса
current_index = 0
posting_active = False
posting_thread = None
start_time = None
post_count = 0
error_count = 0
last_post_time = None

# Инициализация SQLite
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS feedcache (
        id TEXT PRIMARY KEY,
        title TEXT,
        summary TEXT,
        link TEXT,
        source TEXT,
        timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        channel_id TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

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
    prompt = f"""
По ссылке {url} напиши новость на русском в формате:
Заголовок в стиле новостного канала
Основная суть новости в 1-2 предложениях из статьи.

Требования:
- Используй только данные из статьи, ничего не придумывай.
- Не добавляй лишние символы (##, **, [], эмодзи).
- Если данных недостаточно, напиши "Недостаточно данных для пересказа".
- Максимальная длина — 500 символов, обрезай аккуратно.
"""
    data = {
        "model": "google/gemma-2-9b-it:free",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(data), timeout=15)
        response.raise_for_status()
        result = response.json()
        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"].strip()
            if "\n" in content:
                title, summary = content.split("\n", 1)
                return title[:80], summary[:500]
            return content[:80], "Пересказ не получен"
        return "Ошибка: Нет ответа от API", "Ошибка: Нет ответа от API"
    except Exception as e:
        logger.error(f"Ошибка запроса: {str(e)}")
        return "Ошибка: Не удалось обработать новость", "Ошибка: Не удалось обработать новость"

def save_to_feedcache(title, summary, link, source):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    entry = (
        hashlib.md5((link + title).encode()).hexdigest(),  # Хэш от URL + заголовка
        title,
        summary,
        link,
        source,
        datetime.now().isoformat()
    )
    c.execute("INSERT OR REPLACE INTO feedcache (id, title, summary, link, source, timestamp) VALUES (?, ?, ?, ?, ?, ?)", entry)
    conn.commit()
    conn.close()
    logger.info(f"Сохранено в feedcache: {entry[0]}")

def check_duplicate(link, title):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    link_title_hash = hashlib.md5((link + title).encode()).hexdigest()
    c.execute("SELECT id FROM feedcache WHERE id = ?", (link_title_hash,))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_user_channel(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT channel_id FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_user_channel(username, channel_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (username, channel_id) VALUES (?, ?)", (username, channel_id))
    conn.commit()
    conn.close()

def can_post_to_channel(channel_id):
    response = requests.get(f"{TELEGRAM_URL}getChatMember", params={
        "chat_id": channel_id,
        "user_id": requests.get(f"{TELEGRAM_URL}getMe").json()["result"]["id"]
    })
    if response.status_code == 200:
        status = response.json()["result"]["status"]
        return status in ["administrator", "creator"]
    return False

def post_news():
    global current_index, posting_active, post_count, error_count, last_post_time
    while posting_active:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT username, channel_id FROM users")
        users = c.fetchall()
        conn.close()

        if not users:
            logger.info("Нет пользователей с каналами")
            time.sleep(3600)
            continue

        rss_url = RSS_URLS[current_index]
        feed = feedparser.parse(rss_url)

        if not feed.entries:
            logger.warning(f"Нет записей в {rss_url}")
            error_count += 1
        else:
            latest_entry = feed.entries[0]
            link = latest_entry.link
            title, summary = get_article_content(link)
            if "Ошибка" in title:
                error_count += 1
            elif not check_duplicate(link, title):
                message = f"<b>{title}</b> <a href='{link}'>| Источник</a>\n{summary}\n\n<i>Пост сгенерирован ИИ</i>"
                for username, channel_id in users:
                    if can_post_to_channel(channel_id):
                        send_message(channel_id, message)
                        save_to_feedcache(title, summary, link, rss_url.split('/')[2])
                        post_count += 1
                        last_post_time = time.time()
                    else:
                        error_count += 1
                        logger.error(f"Нет прав для постинга в {channel_id}")

        current_index = (current_index + 1) % len(RSS_URLS)
        time.sleep(3600)  # Ждём час

def start_posting_thread():
    global posting_thread, posting_active, start_time
    if posting_thread is None or not posting_thread.is_alive():
        posting_active = True
        start_time = time.time()
        posting_thread = threading.Thread(target=post_news)
        posting_thread.start()
        logger.info("Постинг запущен")

def stop_posting_thread():
    global posting_active, posting_thread
    posting_active = False
    if posting_thread:
        posting_thread.join()
        posting_thread = None
    logger.info("Постинг остановлен")

def get_status():
    uptime = timedelta(seconds=int(time.time() - start_time)) if start_time else "Не запущен"
    next_post = "Не активно"
    if posting_active and last_post_time:
        time_since_last = time.time() - last_post_time
        time_to_next = 3600 - (time_since_last % 3600)
        next_post = f"{int(time_to_next // 60)} мин {int(time_to_next % 60)} сек"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username, channel_id FROM users")
    users = c.fetchall()
    conn.close()
    channels = ", ".join([f"{channel_id} (@{username})" for username, channel_id in users]) if users else "Не привязан"
    return f"""
Статус бота:
Канал: {channels}
Время до следующего поста: {next_post}
Запощенных постов: {post_count}
Аптайм: {uptime}
Ошибок: {error_count}
"""

def get_help():
    return """
Доступные команды:
/start - Привязать канал для постинга
/startposting - Начать постинг новостей раз в час
/stopposting - Остановить постинг
/info - Показать текущий статус бота
/feedcache - Показать содержимое кэша новостей
/feedcacheclear - Очистить кэш новостей
/help - Показать это сообщение
"""

@app.route('/ping', methods=['GET'])
def ping():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if 'message' in update and 'message_id' in update['message']:
        chat_id = update['message']['chat']['id']
        message_text = update['message'].get('text', '')
        username = update['message']['from'].get('username', None)

        if not username:
            send_message(chat_id, "У вас нет username. Установите его в настройках Telegram.")
            return "OK", 200

        user_channel = get_user_channel(username)

        if message_text == '/start':
            if user_channel:
                send_message(chat_id, f"Канал {user_channel} уже привязан. Используйте /startposting для начала.")
            else:
                send_message(chat_id, "Укажите ID канала для постинга (например, @channelname или -1001234567890):")
        elif message_text.startswith('@') or message_text.startswith('-100'):
            channel_id = message_text
            if can_post_to_channel(channel_id):
                save_user_channel(username, channel_id)
                send_message(chat_id, f"Канал {channel_id} привязан. Используйте /startposting для начала.")
            else:
                send_message(chat_id, "Бот не имеет прав администратора в этом канале.")
        elif message_text == '/startposting':
            if user_channel:
                start_posting_thread()
                send_message(chat_id, f"Постинг начат в {user_channel}")
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start")
        elif message_text == '/stopposting':
            if user_channel:
                stop_posting_thread()
                send_message(chat_id, "Постинг остановлен")
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start")
        elif message_text == '/info':
            if user_channel:
                send_message(chat_id, get_status())
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start")
        elif message_text == '/feedcache':
            if user_channel:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("SELECT * FROM feedcache")
                rows = c.fetchall()
                conn.close()
                if not rows:
                    send_message(chat_id, "Feedcache пуст")
                else:
                    cache = [dict(zip(["id", "title", "summary", "link", "source", "timestamp"], row)) for row in rows]
                    send_message(chat_id, "Содержимое feedcache:\n" + json.dumps(cache, ensure_ascii=False, indent=2)[:4096])
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start")
        elif message_text == '/feedcacheclear':
            if user_channel:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM feedcache")
                conn.commit()
                conn.close()
                send_message(chat_id, "Feedcache очищен")
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start")
        elif message_text == '/help':
            if user_channel:
                send_message(chat_id, get_help())
            else:
                send_message(chat_id, "Сначала привяжите канал с помощью /start\n\n" + get_help())

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)