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
duplicate_count = 0
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
    c.execute('''CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        message TEXT,
        link TEXT
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
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", 
              ("model", "google/gemma-2-9b-it:free"))
    conn.commit()
    conn.close()

# Вызываем при старте
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

def get_model():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'model'")
    result = c.fetchone()
    conn.close()
    return result[0] if result else "google/gemma-2-9b-it:free"

def set_model(new_model):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('model', ?)", (new_model,))
    conn.commit()
    conn.close()

def is_valid_language(text):
    # Разрешены латиница, кириллица, цифры, пробелы, базовая пунктуация + : . ;
    return bool(re.match(r'^[A-Za-zА-Яа-я0-9\s.,!?\'"-:;]+$', text))

def clean_title(title):
    # Убираем **, ## и []
    cleaned = re.sub(r'\*\*|\#\#|\[\]', '', title).strip()
    return cleaned

def log_error(message, link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO errors (timestamp, message, link) VALUES (?, ?, ?)", 
              (datetime.now().isoformat(), message, link))
    conn.commit()
    conn.close()

def get_article_content(url, max_attempts=3):
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY не задан")
        log_error("OPENROUTER_API_KEY не задан", url)
        return "Ошибка: OPENROUTER_API_KEY не задан", "Ошибка: OPENROUTER_API_KEY не задан"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Tech_Chronicle",
        "X-Title": "TChNewsBot"
    }
    prompt = get_prompt().format(url=url)
    model = get_model()
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }

    for attempt in range(max_attempts):
        logger.info(f"Запрос к OpenRouter для {url}, попытка {attempt + 1}, модель: {model}")
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, data=json.dumps(data), timeout=15)
            response.raise_for_status()
            result = response.json()
            if "choices" in result and result["choices"]:
                content = result["choices"][0]["message"]["content"].strip()
                if "\n" in content:
                    title, summary = content.split("\n", 1)
                    cleaned_title = clean_title(title)  # Очищаем перед проверкой
                    if is_valid_language(cleaned_title):
                        logger.info(f"Заголовок валиден после очистки: {cleaned_title}")
                        return cleaned_title, summary
                    else:
                        logger.warning(f"Недопустимый язык в заголовке после очистки: {cleaned_title}, перегенерация...")
                        log_error(f"Недопустимый язык в заголовке: {cleaned_title}", url)
                        continue
                return content, "Пересказ не получен"
            logger.error("Нет choices в ответе OpenRouter")
            log_error("Нет choices в ответе OpenRouter", url)
            if attempt == max_attempts - 1:
                return "Ошибка: Нет ответа от API после попыток", "Ошибка: Нет ответа от API"
            continue
        except Exception as e:
            logger.error(f"Ошибка запроса к OpenRouter: {str(e)}")
            log_error(f"Ошибка запроса к OpenRouter: {str(e)}", url)
            if attempt == max_attempts - 1:
                return "Ошибка: Не удалось обработать новость после попыток", "Ошибка: Не удалось обработать новость"
            time.sleep(1)  # Пауза перед повторной попыткой

def save_to_feedcache(title, summary, link, source):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    link_hash = hashlib.md5(link.encode()).hexdigest()
    entry = (link_hash, title, summary, link, source, datetime.now().isoformat())
    try:
        c.execute("INSERT OR REPLACE INTO feedcache (id, title, summary, link, source, timestamp) VALUES (?, ?, ?, ?, ?, ?)", entry)
        conn.commit()
        logger.info(f"Сохранено в feedcache: {link_hash} для {link}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи в feedcache: {str(e)}")
    finally:
        conn.close()

def check_duplicate(link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    link_hash = hashlib.md5(link.encode()).hexdigest()
    c.execute("SELECT id FROM feedcache WHERE id = ?", (link_hash,))
    result = c.fetchone()
    conn.close()
    if result:
        logger.info(f"Найден дубль в feedcache: {link_hash} для {link}")
        return True
    logger.info(f"Дубль не найден: {link_hash} для {link}")
    return False

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
    logger.error(f"Ошибка проверки прав для {channel_id}: {response.text}")
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
    global current_index, posting_active, post_count, error_count, duplicate_count, last_post_time
    while posting_active:
        logger.info(f"Начало цикла постинга, posting_active={posting_active}")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM channels")
        channels = c.fetchall()
        conn.close()
