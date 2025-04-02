from flask import Flask, request
import requests
import feedparser

app = Flask(__name__)

# Твой токен от BotFather
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/"
RSS_URL = "https://www.tomshardware.com/feeds/all"

# Функция отправки сообщения
def send_message(chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"  # Для кликабельных ссылок
    }
    requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

# Функция получения последней новости
def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]  # Берём самую свежую новость
    title = latest_entry.title
    link = latest_entry.link
    message = f"<b>{title}</b>\nИсточник: {link}"
    return message

# Webhook для обработки сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    chat_id = update['message']['chat']['id']
    text = update['message']['text']
    
    # Отправляем последнюю новость в ответ
    news_message = get_latest_news()
    send_message(chat_id, news_message)
    
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=
