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
CHANNEL_ID = os.getenv("CHANNEL_ID")
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
    response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
    if response.status_code != 200:
        logger.error(f"Failed to send message: {response.text}")

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
Заголовок (до 80 символов) в стиле новостного канала.
[Основная суть новости в 1-2 предложениях.]
[Уточняющие детали или цифры из статьи.]

Требования:
- Используй квадратные скобки для каждого абзаца.
- Бери данные только из статьи, ничего не придумывай.
- Максимальная длина пересказа — 1000 символов.
- Разделяй заголовок и пересказ символом \\n.
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
                return title.strip()[:80], summary.strip()[:1000]
            return content[:80], "Пересказ не получен"
        return "Ошибка: Нет ответа от API", "Ошибка: Нет ответа от API"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе")
        return "Ошибка: Таймаут", "Ошибка: Таймаут"
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса: {str(e)}")
        return f"Ошибка: {str(e)}", f"Ошибка: {str(e)}"

def post_latest_news(chat_id):
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    link = latest_entry.link
    
    logger.info(f"Processing news from: {link}")
    title_ru, summary_ru = get_article_content(link)
    full_title = f"{title_ru[:80]} <a href='{link}'>Источник</a>"
    message = f"<b>{full_title}</b>\n{summary_ru}"
    
    send_message(CHANNEL_ID, message)
    send_message(chat_id, "Новость отправлена в @TechChronicleTest")

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Webhook triggered")
    update = request.get_json()
    logger.info(f"Received update: {json.dumps(update, ensure_ascii=False)[:200]}...")
    
    if 'message' not in update or 'message_id' not in update['message']:
        logger.warning("No message or message_id in update, skipping")
        return "OK", 200
    
    chat_id = update['message']['chat']['id']
    message_text = update['message'].get('text', '')

    if message_text == '/test':
        post_latest_news(chat_id)
    
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)