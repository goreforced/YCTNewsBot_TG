from flask import Flask, request
import feedparser
import requests  # Добавляем обратно
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

def get_article_summary(url):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан в переменных окружения"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Tech_Chronicle",
        "X-Title": "TChNewsBot"
    }
    data = {
        "model": "google/gemini-2.5-pro-exp-03-25:free",
        "messages": [
            {
                "role": "user",
                "content": f"По ссылке {url} напиши заголовок на русском (до 100 символов) с источником в конце после '|', и пересказ на русском (до 3900 символов) в лаконичном стиле, без излишней живости и форматирования."
            }
        ]
    }
    try:
        logger.info(f"Using API key: {OPENROUTER_API_KEY[:10]}... (masked)")
        logger.info(f"Requesting summary for URL: {url}")
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(data),
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Raw response: {json.dumps(result, ensure_ascii=False)}")
        
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            logger.info(f"Parsed content: {content[:200]}...")
            lines = content.split("\n", 1)
            title_ru = lines[0].strip()[:100]
            summary_ru = lines[1].strip()[:3900] if len(lines) > 1 else "Пересказ не получен"
            return {"title": title_ru, "summary": summary_ru}
        else:
            return f"Ошибка API: {result.get('error', 'Нет ответа')}"
    except requests.exceptions.Timeout:
        error_msg = "Исключение: Таймаут при запросе к OpenRouter"
        logger.error(error_msg)
        return error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Исключение: {str(e)} - Ответ сервера: {e.response.text if e.response else 'Нет ответа'}"
        logger.error(error_msg)
        return error_msg

def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    link = latest_entry.link
    
    logger.info(f"Processing news from: {link}")
    summary_data = get_article_summary(link)
    
    if isinstance(summary_data, str) and ("Ошибка" in summary_data or "Исключение" in summary_data):
        title_ru = "Ошибка обработки новости"
        summary_ru = summary_data
    else:
        title_ru = summary_data["title"]
        summary_ru = summary_data["summary"]
    
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
