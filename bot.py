from flask import Flask, request
import feedparser
from openai import OpenAI

app = Flask(__name__)

# Твой токен от BotFather
TOKEN = "7977806496:AAHdtcgzJ5mx3sVSaGNSKL-EU9rzjEmmsrI"
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}/"
RSS_URL = "https://www.tomshardware.com/feeds/all"
OPENROUTER_API_KEY = "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"

# Инициализация клиента OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Функция отправки сообщения в Telegram
def send_message(chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)

# Функция получения сводки через OpenRouter
def get_article_summary(url):
    try:
        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://your-site.com",  # Замени на свой сайт, если есть
                "X-Title": "YCTNewsBot"
            },
            model="deepseek/deepseek-v3-base:free",
            messages=[
                {
                    "role": "user",
                    "content": f"По ссылке {url} сделай краткий заголовок на русском (до 100 символов) и пересказ статьи на русском (до 3900 символов)."
                }
            ]
        )
        content = completion.choices[0].message.content
        lines = content.split("\n", 1)
        title_ru = lines[0].strip()[:100]  # Ограничиваем заголовок
        summary_ru = lines[1].strip()[:3900] if len(lines) > 1 else "Пересказ не получен"
        return {"title": title_ru, "summary": summary_ru}
    except Exception as e:
        return f"Исключение: {str(e)}"

# Функция получения новости
def get_latest_news():
    feed = feedparser.parse(RSS_URL)
    latest_entry = feed.entries[0]
    link = latest_entry.link
    
    # Получаем сводку от OpenRouter
    summary_data = get_article_summary(link)
    
    if isinstance(summary_data, str) and "Исключение" in summary_data:
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