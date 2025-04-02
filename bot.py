from flask import Flask, request, jsonify
import feedparser
import requests
from openai import OpenAI
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
TELEGRAM_TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/"
RSS_FEED_URL = "https://www.tomshardware.com/feeds/all"
OPENROUTER_API_KEY = "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"

# Инициализация клиента OpenAI для работы с OpenRouter
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "https://github.com",  # Обязательный заголовок
        "X-Title": "TelegramNewsBot"           # Название вашего приложения
    }
)

def send_telegram_message(chat_id: int, text: str) -> bool:
    """Отправляет сообщение в Telegram чат."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(
            f"{TELEGRAM_API_URL}sendMessage",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {str(e)}")
        return False

def generate_article_summary(url: str) -> dict:
    """Генерирует краткое содержание статьи через OpenRouter."""
    try:
        response = openrouter_client.chat.completions.create(
            model="deepseek/deepseek-v3-base:free",
            messages=[
                {
                    "role": "system",
                    "content": "Ты помогаешь создавать краткие содержания новостей."
                },
                {
                    "role": "user",
                    "content": f"Сделай краткий заголовок (до 100 символов) и пересказ (до 500 слов) статьи по ссылке: {url}"
                }
            ],
            max_tokens=2000,
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        parts = content.split("\n", 1)
        
        return {
            "title": parts[0].strip()[:100],
            "summary": parts[1].strip()[:3900] if len(parts) > 1 else "Не удалось получить пересказ"
        }
    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {str(e)}")
        return {"error": str(e)}

def fetch_latest_news() -> dict:
    """Получает последнюю новость из RSS-ленты."""
    try:
        feed = feedparser.parse(RSS_FEED_URL)
        if not feed.entries:
            raise ValueError("Нет новостей в RSS-ленте")
        return {
            "title": feed.entries[0].title,
            "link": feed.entries[0].link,
            "published": feed.entries[0].published
        }
    except Exception as e:
        logger.error(f"Ошибка парсинга RSS: {str(e)}")
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Обрабатывает входящие webhook-запросы от Telegram."""
    try:
        update = request.get_json()
        chat_id = update['message']['chat']['id']
        
        # Получаем новость
        news = fetch_latest_news()
        if "error" in news:
            send_telegram_message(chat_id, f"Ошибка: {news['error']}")
            return jsonify({"status": "error"}), 200
        
        # Генерируем краткое содержание
        summary = generate_article_summary(news["link"])
        if "error" in summary:
            send_telegram_message(chat_id, f"Ошибка обработки: {summary['error']}")
            return jsonify({"status": "error"}), 200
        
        # Формируем и отправляем сообщение
        message = (
            f"<b>📰 {summary['title']}</b>\n\n"
            f"{summary['summary']}\n\n"
            f"<a href='{news['link']}'>Читать полностью</a>"
        )
        send_telegram_message(chat_id, message)
        
        return jsonify({"status": "success"}), 200
    
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/healthcheck', methods=['GET'])
def health_check():
    """Проверка работоспособности сервиса."""
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)