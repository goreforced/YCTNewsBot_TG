from flask import Flask, request
import requests
import feedparser
import http.client
import json

app = Flask(__name__)

# Твой токен от BotFather
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/"
RSS_URL = "https://www.tomshardware.com/feeds/all"
TINQ_API_KEY = "SZoacti4MjZ9OXsfSnomJwf8NRFcrShaX8bluJwb5c1de38b"  # Твой ключ от Tinq.ai

# Функция отправки сообщения в Telegram
def send_message(chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

# Функция извлечения текста статьи через Tinq.ai
def extract_article(url):
    conn = http.client.HTTPSConnection("tinq.ai")
    payload = json.dumps({"url": url})
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TINQ_API_KEY}"
    }
    conn.request("POST", "/api/v1/extractor", payload, headers)
    res = conn.getresponse()
    data = res.read()
    result = json.loads(data.decode("utf-8"))
    return result.get("text", "Ошибка извлечения текста")

# Функция получения новости
def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    title = latest_entry.title
    link = latest_entry.link
    
    # Извлекаем текст статьи через Tinq.ai
    article_text = extract_article(link)
    
    # Берём первые 200 символов текста как сводку (временно, без суммаризации)
    summary_ru = article_text[:200] + "..." if article_text else "Не удалось извлечь текст"
    
    # Форматируем сообщение
    message = f"<b>{title}</b>\n{summary_ru}\n<a href='{link}'>Источник</a>"
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
