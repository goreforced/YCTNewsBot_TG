from flask import Flask, request
import requests
import feedparser
import http.client
import json
from googletrans import Translator

app = Flask(__name__)

# Твой токен от BotFather
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/"
RSS_URL = "https://www.tomshardware.com/feeds/all"
TINQ_API_KEY = "SZoacti4MjZ9OXsfSnomJwf8NRFcrShaX8bluJwb5c1de38b"  # Твой ключ от Tinq.ai
translator = Translator()

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
    try:
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
        if res.status == 200 and "article" in result["data"] and "article" in result["data"]["article"]:
            return {
                "text": result["data"]["article"]["article"],
                "title": result["data"]["article"]["title"]
            }
        else:
            return f"Ошибка API: {res.status} - {result.get('message', 'Нет текста')}"
    except Exception as e:
        return f"Исключение: {str(e)}"

# Функция создания динамического заголовка
def make_dynamic_title(title_en):
    # Переводим заголовок на русский
    title_ru = translator.translate(title_en, dest="ru").text
    
    # Сокращаем и перефразируем
    if "exclusive" in title_en.lower():
        title_ru = title_ru.replace("эксклюзивы для Amazon Prime", "только для Prime")
    if "scalpers" in title_en.lower():
        title_ru += ", что бесит перекупщиков"
    if "RTX" in title_en or "RX" in title_en:
        title_ru = title_ru.replace("графические процессоры", "видеокарты")
    
    return title_ru[:100]  # Ограничиваем до 100 символов

# Функция получения новости
def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    title_en = latest_entry.title  # Оригинальный заголовок из RSS
    link = latest_entry.link
    summary = latest_entry.summary if "summary" in latest_entry else "Нет описания"
    
    # Пробуем извлечь текст статьи
    article_data = extract_article(link)
    
    # Если ошибка, берём summary из RSS и переводим
    if isinstance(article_data, str) and ("Ошибка" in article_data or "Исключение" in article_data):
        summary_ru = translator.translate(summary, dest="ru").text
        title_ru = make_dynamic_title(title_en)
    else:
        summary_ru = article_data["text"]  # Полный текст статьи
        title_ru = make_dynamic_title(article_data["title"])  # Заголовок из Tinq.ai
    
    # Форматируем сообщение
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