from flask import Flask, request
import requests
import feedparser
import http.client
import json
from googletrans import Translator

app = Flask(__name__)

# Токен вашего бота от BotFather
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/"
RSS_URL = "https://www.tomshardware.com/feeds/all"
TINQ_API_KEY = "SZoacti4MjZ9OXsfSnomJwf8NRFcrShaX8bluJwb5c1de38b"
translator = Translator()

# Максимальная длина сообщения в Telegram
MAX_MESSAGE_LENGTH = 4096

def send_message(chat_id, text):
    """Отправляет сообщение в Telegram, разбивая его на части, если оно превышает лимит."""
    for chunk in split_text(text, MAX_MESSAGE_LENGTH):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML"
        }
        requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

def extract_article(url):
    """Извлекает полный текст статьи по URL с помощью Tinq.ai."""
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
        if res.status == 200 and "text" in result:
            return result["text"]
        else:
            return f"Ошибка API: {res.status} - {result.get('message', 'Нет текста')}"
    except Exception as e:
        return f"Исключение: {str(e)}"

def summarize_text(text):
    """Создает сводку текста с помощью Tinq.ai."""
    try:
        conn = http.client.HTTPSConnection("tinq.ai")
        payload = json.dumps({"text": text})
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TINQ_API_KEY}"
        }
        conn.request("POST", "/api/v1/summarize", payload, headers)
        res = conn.getresponse()
        data = res.read()
        result = json.loads(data.decode("utf-8"))
        if res.status == 200 and "summary" in result:
            return result["summary"]
        else:
            return f"Ошибка API: {res.status} - {result.get('message', 'Нет сводки')}"
    except Exception as e:
        return f"Исключение: {str(e)}"

def get_latest_news():
    """Получает последнюю новость из RSS, извлекает и суммирует текст, переводит на русский."""
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    title = latest_entry.title
    link = latest_entry.link

    # Извлекаем полный текст статьи
    full_text = extract_article(link)
    
    # Если извлечение не удалось, используем summary из RSS
    if "Ошибка" in full_text or "Исключение" in full_text:
        summary = latest_entry.summary if "summary" in latest_entry else "Нет описания"
    else:
        summary = summarize_text(full_text)
    
    # Переводим сводку на русский
    summary_ru = translator.translate(summary, dest="ru").text

    # Формируем сообщение
    message = f"<b>{title}</b>\n{summary_ru}\n<a href='{link}'>Источник</a>"
    return message

def split_text(text, max_length):
    """Разбивает текст на части, не превышающие max_length символов."""
    for i in range(0, len(text), max_length):
        yield text[i:i + max_length]

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обрабатывает входящие сообщения от Telegram."""
    update = request.get_json()
    chat_id = update['message']['chat']['id']
    news_message = get_latest_news()
    send_message(chat_id, news_message)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
    # Если ошибка, берём summary из RSS и переводим
    if "Ошибка" in article_text or "Исключение" in article_text:
        summary = latest_entry.summary if "summary" in latest_entry else "Нет описания"
        summary_ru = translator.translate(summary, dest="ru").text[:200] + "..."
    else:
        summary_ru = article_text
    
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
