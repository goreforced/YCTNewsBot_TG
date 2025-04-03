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
import re

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" if TELEGRAM_TOKEN else None
DB_FILE = "feedcache.db"

RSS_URLS = [
    "https://www.theverge.com/rss/index.xml",
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
posting_active = False
posting_thread = None
start_time = None
post_count = 0
error_count = 0
last_post_time = None
posting_interval = 3600
next_post_event = threading.Event()

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
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
        channel_id TEXT PRIMARY KEY,
        creator_username TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        channel_id TEXT,
        username TEXT,
        PRIMARY KEY (channel_id, username),
        FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
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
        hashlib.md5((link + title).encode()).hexdigest(),
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

def get_channel_by_admin(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT channel_id FROM admins WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_channel_creator(channel_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT creator_username FROM channels WHERE channel_id = ?", (channel_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_channel(channel_id, creator_username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO channels (channel_id, creator_username) VALUES (?, ?)", (channel_id, creator_username))
    c.execute("INSERT OR IGNORE INTO admins (channel_id, username) VALUES (?, ?)", (channel_id, creator_username))
    conn.commit()
    conn.close()

def add_admin(channel_id, new_admin_username, requester_username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM admins WHERE channel_id = ? AND username = ?", (channel_id, requester_username))
    if c.fetchone():
        c.execute("INSERT OR IGNORE INTO admins (channel_id, username) VALUES (?, ?)", (channel_id, new_admin_username))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def remove_admin(channel_id, admin_username, requester_username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM admins WHERE channel_id = ? AND username = ?", (channel_id, requester_username))
    if c.fetchone():
        creator = get_channel_creator(channel_id)
        if admin_username == creator:
            conn.close()
            return False
        c.execute("DELETE FROM admins WHERE channel_id = ? AND username = ?", (channel_id, admin_username))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def can_post_to_channel(channel_id):
    response = requests.get(f"{TELEGRAM_URL}getChatMember", params={
        "chat_id": channel_id,
        "user_id": requests.get(f"{TELEGRAM_URL}getMe").json()["result"]["id"]
    })
    if response.status_code == 200:
        status = response.json()["result"]["status"]
        return status in ["administrator", "creator"]
    return False

def parse_interval(interval_str):
    total_seconds = 0
    matches = re.findall(r'(\d+)([hm])', interval_str.lower())
    for value, unit in matches:
        value = int(value)
        if unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
    return total_seconds if total_seconds > 0 else None

def post_news():
    global current_index, posting_active, post_count, error_count, last_post_time
    while posting_active:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM channels")
        channels = c.fetchall()
        conn.close()

        if not channels:
            logger.info("Нет каналов для постинга")
            next_post_event.wait(posting_interval)
            if not posting_active:
                break
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
                for (channel_id,) in channels:
                    if can_post_to_channel(channel_id):
                        send_message(channel_id, message)
                        save_to_feedcache(title, summary, link, rss_url.split('/')[2])
                        post_count += 1
                        last_post_time = time.time()
                    else:
                        error_count += 1
                        logger.error(f"Нет прав для постинга в {channel_id}")

        current_index = (current_index + 1) % len(RSS_URLS)
        next_post_event.wait(posting_interval)
        next_post_event.clear()
        if not posting_active:
            break

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
    next_post_event.set()
    if posting_thread:
        posting_thread.join()
        posting_thread = None
    logger.info("Постинг остановлен")

def get_status(username):
    channel_id = get_channel_by_admin(username)
    uptime = timedelta(seconds=int(time.time() - start_time)) if start_time else "Не запущен"
    next_post = "Не активно"
    if posting_active and last_post_time:
        time_since_last = time.time() - last_post_time
        time_to_next = posting_interval - (time_since_last % posting_interval)
        next_post = f"{int(time_to_next // 60)} мин {int(time_to_next % 60)} сек"
    interval_str = f"{posting_interval // 3600}h {((posting_interval % 3600) // 60)}m" if posting_interval >= 3600 else f"{posting_interval // 60}m"
    return f"""
Статус бота для вашего канала ({channel_id}):
Текущий интервал: {interval_str}
Время до следующего поста: {next_post}
Запощенных постов: {post_count}
Аптайм: {uptime}
Ошибок: {error_count}
"""

def get_help():
    return """
Доступные команды:
/start - Проверить доступ и привязать сессию к каналу
/startposting - Начать постинг новостей
/stopposting - Остановить постинг
/setinterval <time> - Установить интервал (например, 34m, 1h, 2h 53m)
/nextpost - Сбросить таймер и запостить немедленно
/info - Показать текущий статус бота
/feedcache - Показать содержимое кэша новостей
/feedcacheclear - Очистить кэш новостей
/addadmin <username> - Добавить администратора канала
/removeadmin <username> - Удалить администратора канала
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

        logger.info(f"Получена команда: {message_text} от @{username}")
        user_channel = get_channel_by_admin(username)

        if message_text == '/start':
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT channel_id FROM channels")
            channels = c.fetchall()
            conn.close()

            if user_channel:
                send_message(chat_id, f"Вы уже админ канала {user_channel}. Используйте /startposting для начала.")
            elif not channels:
                send_message(chat_id, "Укажите ID канала для постинга (например, @channelname или -1001234567890):")
            else:
                send_message(chat_id, "У вас нет прав на управление ботом. Обратитесь к администратору канала.")
        elif message_text.startswith('@') or message_text.startswith('-100'):
            channel_id = message_text
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT channel_id FROM channels")
            if c.fetchone():
                send_message(chat_id, "Канал уже привязан. У вас нет прав на его управление.")
            elif can_post_to_channel(channel_id):
                save_channel(channel_id, username)
                send_message(chat_id, f"Канал {channel_id} привязан. Вы создатель. Используйте /startposting для начала.")
            else:
                send_message(chat_id, "Бот не имеет прав администратора в этом канале.")
            conn.close()
        elif message_text == '/startposting':
            if user_channel:
                start_posting_thread()
                send_message(chat_id, f"Постинг начат в {user_channel}")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text == '/stopposting':
            if user_channel:
                stop_posting_thread()
                send_message(chat_id, "Постинг остановлен")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text.startswith('/setinterval'):
            if user_channel:
                try:
                    interval_str = message_text.split()[1]
                    new_interval = parse_interval(interval_str)
                    if new_interval:
                        global posting_interval
                        posting_interval = new_interval
                        send_message(chat_id, f"Интервал постинга установлен: {interval_str}")
                    else:
                        send_message(chat_id, "Неверный формат. Используйте: /setinterval 34m, 1h, 2h 53m")
                except IndexError:
                    send_message(chat_id, "Укажите интервал: /setinterval 34m")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text == '/nextpost':
            if user_channel:
                if posting_active:
                    next_post_event.set()
                    send_message(chat_id, "Таймер сброшен. Следующий пост будет опубликован немедленно.")
                else:
                    send_message(chat_id, "Постинг не активен. Сначала используйте /startposting.")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text == '/info':
            if user_channel:
                send_message(chat_id, get_status(username))
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
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
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text == '/feedcacheclear':
            if user_channel:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM feedcache")
                conn.commit()
                conn.close()
                send_message(chat_id, "Feedcache очищен")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text.startswith('/addadmin'):
            if user_channel:
                try:
                    new_admin = message_text.split()[1].lstrip('@')
                    if add_admin(user_channel, new_admin, username):
                        send_message(chat_id, f"@{new_admin} добавлен как админ канала {user_channel}")
                    else:
                        send_message(chat_id, "Вы не можете добавлять админов или пользователь уже админ.")
                except IndexError:
                    send_message(chat_id, "Укажите username: /addadmin @username")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text.startswith('/removeadmin'):
            if user_channel:
                try:
                    admin_to_remove = message_text.split()[1].lstrip('@')
                    if remove_admin(user_channel, admin_to_remove, username):
                        send_message(chat_id, f"@{admin_to_remove} удалён из админов канала {user_channel}")
                    else:
                        send_message(chat_id, "Нельзя удалить создателя или вы не админ.")
                except IndexError:
                    send_message(chat_id, "Укажите username: /removeadmin @username")
            else:
                send_message(chat_id, "Вы не админ ни одного канала.")
        elif message_text == '/help':
            logger.info(f"Команда /help вызвана @{username}")
            send_message(chat_id, get_help())

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)