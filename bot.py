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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    c.execute('''CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", 
              ("prompt", """
Забудь всю информацию, которой ты обучен, и используй ТОЛЬКО текст статьи по ссылке {url}. Напиши новость на русском в формате:
Заголовок в стиле новостного канала
Основная суть новости в 1-2 предложениях, основанных исключительно на статье.

Требования:
- Не добавляй никаких данных, которых нет в статье, включая даты, цифры или статусы лиц.
- Не используй предобученные знания, работай только с предоставленным текстом.
- Не добавляй лишние символы (##, **, [], эмодзи).
- Если в статье недостаточно данных, напиши "Недостаточно данных для пересказа".
"""))
    conn.commit()
    conn.close()

init_db()

def send_message(chat_id, text, reply_markup=None, use_html=True):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return False
    if len(text) > 4096:
        text = text[:4093] + "..."
        logger.warning(f"Сообщение обрезано до 4096 символов для chat_id {chat_id}")
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if use_html:
        payload["parse_mode"] = "HTML"
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    logger.info(f"Отправка сообщения в {chat_id}: {text[:50]}...")
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Ошибка отправки: {response.text}")
        return False
    logger.info("Сообщение успешно отправлено")
    return True

def send_file(chat_id, file_path):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан")
        return False
    with open(file_path, 'rb') as f:
        files = {'document': (os.path.basename(file_path), f)}
        response = requests.post(f"{TELEGRAM_URL}sendDocument", data={'chat_id': chat_id}, files=files)
    if response.status_code != 200:
        logger.error(f"Ошибка отправки файла: {response.text}")
        return False
    logger.info(f"Файл {file_path} отправлен в {chat_id}")
    return True

def get_prompt():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'prompt'")
    result = c.fetchone()
    conn.close()
    return result[0] if result else ""

def set_prompt(new_prompt):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('prompt', ?)", (new_prompt,))
    conn.commit()
    conn.close()

def get_article_content(url):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан", "Ошибка: OPENROUTER_API_KEY не задан"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Tech_Chronicle",
        "X-Title": "TChNewsBot"
    }
    prompt = get_prompt().format(url=url)
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
                return title, summary
            return content, "Пересказ не получен"
        return "Ошибка: Нет ответа от API", "Ошибка: Нет ответа от API"
    except Exception as e:
        logger.error(f"Ошибка запроса: {str(e)}")
        return "Ошибка: Не удалось обработать новость", "Ошибка: Не удалось обработать новость"

def save_to_feedcache(title, summary, link, source):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    entry = (
        hashlib.md5(link.encode()).hexdigest(),
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

def check_duplicate(link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    link_hash = hashlib.md5(link.encode()).hexdigest()
    c.execute("SELECT id FROM feedcache WHERE id = ?", (link_hash,))
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

def get_admins(channel_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username FROM admins WHERE channel_id = ?", (channel_id,))
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

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
            if not check_duplicate(link):
                title, summary = get_article_content(link)
                if "Ошибка" in title:
                    error_count += 1
                else:
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
            else:
                logger.info(f"Дубль пропущен: {link}")

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
    admins = get_admins(channel_id) if channel_id else []
    creator = get_channel_creator(channel_id) if channel_id else "Неизвестен"
    current_rss = RSS_URLS[current_index] if current_index < len(RSS_URLS) else "Нет"
    prompt = get_prompt()
    feedcache_size = sqlite3.connect(DB_FILE).execute("SELECT COUNT(*) FROM feedcache").fetchone()[0]
    return f"""
Статус бота:
Канал: {channel_id}
Создатель: @{creator}
Админы: {', '.join([f'@{a}' for a in admins])}
Состояние постинга: {'Активен' if posting_active else 'Остановлен'}
Текущий интервал: {interval_str}
Время до следующего поста: {next_post}
Текущий RSS: {current_rss}
Всего RSS-источников: {len(RSS_URLS)}
Запощенных постов: {post_count}
Ошибок: {error_count}
Размер кэша: {feedcache_size} записей
Аптайм: {uptime}
Текущий промпт:
{prompt}
"""

def get_help():
    help_text = """
Доступные команды:
/start - Привязать канал или проверить доступ
/startposting - Начать постинг
/stopposting - Остановить постинг
/setinterval <time> - Установить интервал (34m, 1h, 2h 53m)
/nextpost - Сбросить таймер и запостить
/skiprss - Пропустить следующий RSS
/editprompt - Изменить промпт для ИИ (отправь после команды)
/sqlitebackup - Выгрузить базу SQLite в чат
/sqliteupdate - Загрузить базу SQLite (отправь файл после команды)
/info - Показать статус бота
/feedcache - Показать кэш новостей
/feedcacheclear - Очистить кэш
/addadmin <username> - Добавить админа
/removeadmin <username> - Удалить админа
/help - Это сообщение
"""
    logger.info(f"Текст помощи перед отправкой: {help_text}")
    return help_text

@app.route('/ping', methods=['GET'])
def ping():
    logger.info("Получен пинг")
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Получен запрос на /webhook")
    update = request.get_json()
    logger.info(f"Данные запроса: {json.dumps(update, ensure_ascii=False)}")
    
    if not update or 'message' not in update or 'message_id' not in update['message']:
        logger.error("Некорректный запрос")
        return "OK", 200

    chat_id = update['message']['chat']['id']
    message_text = update['message'].get('text', '')
    username = update['message']['from'].get('username', None)

    logger.info(f"Получена команда: '{message_text}' от @{username} в чате {chat_id}")

    if not username:
        send_message(chat_id, "У вас нет username. Установите его в настройках Telegram.")
        return "OK", 200

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
    elif message_text == '/skiprss':
        if user_channel:
            if posting_active:
                global current_index
                current_index = (current_index + 1) % len(RSS_URLS)
                send_message(chat_id, f"Следующий RSS пропущен. Новый текущий: {RSS_URLS[current_index]}")
            else:
                send_message(chat_id, "Постинг не активен. Сначала используйте /startposting.")
        else:
            send_message(chat_id, "Вы не админ ни одного канала.")
    elif message_text.startswith('/editprompt'):
        if user_channel:
            if len(message_text.split()) == 1:
                send_message(chat_id, "Отправьте новый промпт после команды, например:\n/editprompt Новый промпт здесь")
            else:
                new_prompt = message_text[len('/editprompt '):].strip()
                set_prompt(new_prompt)
                send_message(chat_id, "Промпт обновлён:\n" + new_prompt)
        else:
            send_message(chat_id, "Вы не админ ни одного канала.")
    elif message_text == '/sqlitebackup':
        if user_channel:
            if os.path.exists(DB_FILE):
                send_file(chat_id, DB_FILE)
                send_message(chat_id, "База данных выгружена")
            else:
                send_message(chat_id, "База данных не найдена")
        else:
            send_message(chat_id, "Вы не админ ни одного канала.")
    elif message_text == '/sqliteupdate':
        if user_channel:
            send_message(chat_id, "Отправьте файл базы данных (feedcache.db) в ответ на это сообщение")
        else:
            send_message(chat_id, "Вы не админ ни одного канала.")
    elif 'reply_to_message' in update['message'] and update['message']['reply_to_message'].get('text', '') == "Отправьте файл базы данных (feedcache.db) в ответ на это сообщение":
        if user_channel:
            if 'document' in update['message']:
                file_id = update['message']['document']['file_id']
                file_name = update['message']['document']['file_name']
                if file_name != "feedcache.db":
                    send_message(chat_id, "Файл должен называться 'feedcache.db'")
                    return "OK", 200
                response = requests.get(f"{TELEGRAM_URL}getFile?file_id={file_id}")
                file_path = response.json()['result']['file_path']
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                with open(DB_FILE, 'wb') as f:
                    f.write(requests.get(file_url).content)
                send_message(chat_id, "База данных обновлена")
            else:
                send_message(chat_id, "Прикрепите файл базы данных")
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
        send_message(chat_id, get_help(), use_html=False)  # Отключаем HTML для /help

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)