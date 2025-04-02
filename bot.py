from flask import Flask, request
import feedparser
import requests
import json
import logging
import os

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен Telegram и ключ OpenRouter из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/" if TELEGRAM_TOKEN else None
RSS_URL = "https://www.tomshardware.com/feeds/all"

# Функция отправки сообщения в Telegram
def send_message(chat_id, text):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан в переменных окружения")
        return  # Ничего не отправляем, просто выходим
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    logger.info(f"Sending message to chat_id {chat_id}: {text[:50]}...")
    requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

# Функция получения сводки через OpenRouter
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
        "model": "deepseek/deepseek-v3-base:free",
        "messages": [
            {
                "role": "user",
                "content": f"По ссылке {url} сделай краткий заголовок на русском (до 100 символов) и пересказ статьи на русском (до 3900 символов)."
            }
        ]
    }
    try:
        logger.info(f"Using API key: {OPENROUTER_API_KEY[:10]}... (masked)")
        logger.info(f"Requesting summary for URL: {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Data: {json.dumps(data, ensure_ascii=False)}")
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(data)
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Response: {json.dumps(result, ensure_ascii=False)[:200]}...")
        
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            lines = content.split("\n", 1)
            title_ru = lines[0].strip()[:100]
            summary_ru = lines[1].strip()[:3900] if len(lines) > 1 else "Пересказ не получен"
            return {"title": title_ru, "summary": summary_ru}
        else:
            return f"Ошибка API: {result.get('error', 'Нет ответа')}"
    except requests.exceptions.RequestException as e:
        error_msg = f"Исключение: {str(e)} - Ответ сервера: {e.response.text if e.response else 'Нет ответа'}"
        logger.error(error_msg)
        return error_msg

# Функция получения новости
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
    
    message = f"<b>{title_ru}</b>\n{summary_ru}\n<a href='{link}'>Источник</a>"
    return message

# Webhook для обработки сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    chat_id = update['message']['chat']['id']
    news_message = get_latest_news()
    send_message(chat_id, news_message)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
