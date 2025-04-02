from flask import Flask, request
import feedparser
import requests
import json
import logging
import os

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" if TELEGRAM_TOKEN else None
RSS_URL = "https://www.tomshardware.com/feeds/all"

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
    requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

def get_article_title(url):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-site.com",
        "X-Title": "YCTNewsBot"
    }
    data = {
        "model": "bytedance-research/ui-tars-72b:free",
        "messages": [
            {
                "role": "user",
                "content": f"По ссылке {url} напиши заголовок на русском (до 100 символов) с источником в конце после '|' в стиле новостного канала."
            }
        ]
    }
    try:
        logger.info(f"Requesting title for URL: {url}")
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Title response: {json.dumps(result, ensure_ascii=False)}")
        
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"].strip()[:100]
        return "Ошибка: Нет заголовка от API"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе заголовка")
        return "Ошибка: Таймаут заголовка"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка заголовка: {str(e)}")
        return f"Ошибка: {str(e)}"

def get_article_summary(url):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан в переменных окружения"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-site.com",
        "X-Title": "YCTNewsBot"
    }
    data = {
        "model": "bytedance-research/ui-tars-72b:free",
        "messages": [
            {
                "role": "user",
                "content": f"""
Напиши новость по ссылке {url} в следующем формате:

[Первый абзац: 1-2 предложения, основная суть новости. Чётко и без воды.]
[Второй абзац: уточняющие детали, важные цифры или контекст (если есть).]
[Третий абзац (необязательно): краткий итог или дополнительная важная информация.]

Требования:
- Отвечай на русском языке.
- Строго следуй формату.
- Без аналитики, предположений, выводов, мнений.
- Не используй вводные фразы, вроде "новые данные показывают" или "это может означать".
- Без оформления, маркеров и списков.
- Максимальная длина — 1000 символов.
"""
            }
        ]
    }
    try:
        logger.info(f"Requesting summary for URL: {url}")
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Summary response: {json.dumps(result, ensure_ascii=False)}")
        
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"].strip()[:1000]
        return "Ошибка: Нет пересказа от API"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе пересказа")
        return "Ошибка: Таймаут пересказа"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка пересказа: {str(e)}")
        return f"Ошибка: {str(e)}"

def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    link = latest_entry.link
    
    logger.info(f"Processing news from: {link}")
    title_ru = get_article_title(link)
    summary_ru = get_article_summary(link)
    
    if "Ошибка" in title_ru or "Ошибка" in summary_ru:
        message = f"<b>{title_ru}</b>\n{summary_ru}"
    else:
        message = f"<b>{title_ru}</b>\n{summary_ru}"
    
    return message

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Webhook triggered")
    update = request.get_json()
    logger.info(f"Received update: {json.dumps(update, ensure_ascii=False)[:200]}...")
    chat_id = update['message']['chat']['id']
    news_message = get_latest_news()
    send_message(chat_id, news_message)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
