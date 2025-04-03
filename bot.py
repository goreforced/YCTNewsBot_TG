import asyncio
import aiohttp
import sqlite3
import hashlib
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import feedparser
import json
from functools import lru_cache

# ==================== Конфигурация ====================
class Config:
    def __init__(self):
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
        self.CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
        self.ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
        self.RSS_URLS = [
            "https://www.theverge.com/rss/index.xml",
            "https://www.windowscentral.com/feed",
            "https://www.windowslatest.com/feed/",
            "https://9to5google.com/feed/",
            "https://9to5mac.com/feed/",
            "https://www.androidcentral.com/feed",
            "https://arstechnica.com/feed/",
            "https://uk.pcmag.com/rss",
            "https://www.bleepingcomputer.com/feed/",
            "https://www.androidauthority.com/news/feed/",
            "https://feeds.feedburner.com/Techcrunch"
        ]
        self.DB_FILE = os.getenv("DB_FILE", "news_bot.db")
        self.MAX_POSTS_PER_REQUEST = 2
        self.SUMMARY_MAX_LENGTH = 500

config = Config()

# ==================== Настройка логирования ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ==================== Модели данных ====================
@dataclass
class Article:
    title: str
    summary: str
    link: str
    source: str
    published_at: datetime
    post_id: Optional[str] = None

@dataclass
class PendingPost:
    article: Article
    state: str = "pending"  # pending/editing_title/editing_summary/approved/rejected

# ==================== Хранилище данных ====================
class Database:
    def __init__(self, db_file: str):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self._init_db()
    
    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS published_articles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    link TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    def add_article(self, article: Article) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO published_articles 
                    (id, title, summary, link, source, published_at) 
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        hashlib.md5(article.link.encode()).hexdigest(),
                        article.title,
                        article.summary,
                        article.link,
                        article.source,
                        article.published_at.isoformat()
                    )
                )
            return True
        except sqlite3.IntegrityError as e:
            logger.warning(f"Article already exists: {article.link}")
            return False
    
    def article_exists(self, link: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM published_articles WHERE link = ?",
            (link,)
        )
        return bool(cursor.fetchone())
    
    def get_all_articles(self) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(
            "SELECT title, summary, link, source, published_at FROM published_articles"
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def clear_all_articles(self) -> int:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM published_articles")
            return cursor.rowcount

db = Database(config.DB_FILE)

# ==================== Клиент Telegram ====================
class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.session = aiohttp.ClientSession()
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.pending_posts: Dict[int, Dict[str, PendingPost]] = {}
    
    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True
    ) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview
        }
        
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        
        try:
            async with self.session.post(
                f"{self.base_url}sendMessage",
                json=payload
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Telegram API error: {error}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    async def answer_callback_query(self, callback_query_id: str):
        try:
            async with self.session.post(
                f"{self.base_url}answerCallbackQuery",
                json={"callback_query_id": callback_query_id}
            ):
                pass
        except Exception as e:
            logger.error(f"Error answering callback: {e}")
    
    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict
    ) -> bool:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps(reply_markup)
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}editMessageReplyMarkup",
                json=payload
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            return False
    
    async def close(self):
        await self.session.close()

# ==================== Клиент OpenRouter ====================
class OpenRouterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = aiohttp.ClientSession()
    
    @lru_cache(maxsize=100)
    async def summarize_article(self, url: str) -> Tuple[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/Tech_Chronicle",
            "X-Title": "TChNewsBot"
        }
        
        prompt = f"""По ссылке {url} напиши новость на русском в следующем формате:
Заголовок в стиле новостного канала
Основная суть новости в 1-2 предложениях из статьи.

Требования:
- Бери данные только из статьи, ничего не придумывай.
- Внимательно проверяй даты и числа в статье, не путай их.
- Не добавляй "| Источник", названия сайтов или эмодзи.
- Не используй форматирование вроде ##, ** или [].
- Максимальная длина пересказа — {config.SUMMARY_MAX_LENGTH} символов."""
        
        try:
            async with self.session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": "google/gemma-2-9b-it:free",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=20
            ) as resp:
                data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                if "\n" in content:
                    title, summary = content.split("\n", 1)
                    return title.strip(), summary.strip()[:config.SUMMARY_MAX_LENGTH]
                return content[:80], "Пересказ не получен"
        except Exception as e:
            logger.error(f"OpenRouter error: {e}")
            return f"Ошибка: {str(e)}", f"Ошибка: {str(e)}"
    
    async def close(self):
        await self.session.close()

# ==================== RSS пр��цессор ====================
class RSSProcessor:
    def __init__(self, rss_urls: List[str]):
        self.urls = rss_urls
    
    async def fetch_latest_articles(self, limit: int = 2) -> List[Article]:
        tasks = [self._fetch_feed(url) for url in self.urls[:limit*2]]  # Берем больше для резерва
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        articles = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error fetching feed: {result}")
                continue
            if result and not db.article_exists(result.link):
                articles.append(result)
                if len(articles) >= limit:
                    break
        
        return articles
    
    async def _fetch_feed(self, url: str) -> Optional[Article]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    text = await resp.text()
                    feed = feedparser.parse(text)
                    
                    if not feed.entries:
                        return None
                    
                    latest_entry = feed.entries[0]
                    return Article(
                        title=latest_entry.title,
                        summary="",  # Будет заполнено позже
                        link=latest_entry.link,
                        source=url.split('/')[2],
                        published_at=datetime.now()
                    )
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return None

# ==================== Основное приложение ====================
class NewsBotApplication:
    def __init__(self):
        self.bot = TelegramBot(config.TELEGRAM_TOKEN)
        self.openrouter = OpenRouterClient(config.OPENROUTER_API_KEY)
        self.rss_processor = RSSProcessor(config.RSS_URLS)
    
    async def handle_update(self, update: dict):
        if "message" in update:
            await self._handle_message(update["message"])
        elif "callback_query" in update:
            await self._handle_callback(update["callback_query"])
    
    async def _handle_message(self, message: dict):
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()
        
        if not text.startswith("/"):
            await self._handle_text_input(chat_id, text)
            return
        
        command = text.split()[0].lower()
        
        if command == "/fetch":
            await self.fetch_news(chat_id)
        elif command == "/post":
            await self.post_latest_news(chat_id)
        elif command == "/feedcache":
            await self.show_feedcache(chat_id)
        elif command == "/feedcacheclear" and chat_id in config.ADMIN_IDS:
            await self.clear_feedcache(chat_id)
        elif command == "/stats":
            await self.show_stats(chat_id)
        elif command == "/help":
            await self.show_help(chat_id)
    
    async def _handle_text_input(self, chat_id: int, text: str):
        if chat_id not in self.bot.pending_posts:
            return
        
        for post_id, post in self.bot.pending_posts[chat_id].items():
            if post.state == "editing_title":
                post.article.title = text
                post.state = "editing_summary"
                await self.bot.send_message(
                    chat_id,
                    "Теперь введите новый текст новости:",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "Оставить текущий", "callback_data": f"keep_summary_{post_id}"}
                        ]]
                    }
                )
                return
            
            elif post.state == "editing_summary":
                post.article.summary = text
                post.state = "pending"
                await self._show_post_for_review(chat_id, post_id, post)
                return
    
    async def _handle_callback(self, callback_query: dict):
        chat_id = callback_query["message"]["chat"]["id"]
        data = callback_query["data"]
        message_id = callback_query["message"]["message_id"]
        
        await self.bot.answer_callback_query(callback_query["id"])
        
        if "_" not in data:
            return
        
        action, post_id = data.split("_", 1)
        
        if chat_id not in self.bot.pending_posts or post_id not in self.bot.pending_posts[chat_id]:
            await self.bot.send_message(chat_id, "Пост не найден или устарел")
            return
        
        post = self.bot.pending_posts[chat_id][post_id]
        
        if action == "approve":
            await self._publish_post(chat_id, post_id, post)
        elif action == "reject":
            del self.bot.pending_posts[chat_id][post_id]
            await self.bot.send_message(chat_id, "Пост отклонен")
        elif action == "edit":
            post.state = "editing_title"
            await self.bot.send_message(
                chat_id,
                "Введите новый заголовок:",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Оставить текущий", "callback_data": f"keep_title_{post_id}"}
                    ]]
                }
            )
        elif action == "keep_title":
            post.state = "editing_summary"
            await self.bot.send_message(
                chat_id,
                "Введите новый текст новости:",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "Оставить текущий", "callback_data": f"keep_summary_{post_id}"}
                    ]]
                }
            )
        elif action == "keep_summary":
            post.state = "pending"
            await self._show_post_for_review(chat_id, post_id, post)
    
    async def _show_post_for_review(self, chat_id: int, post_id: str, post: PendingPost):
        message_text = f"<b>{post.article.title}</b>\n{post.article.summary}\n\n<a href='{post.article.link}'>Источник</a>"
        
        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Одобрить", "callback_data": f"approve_{post_id}"},
                    {"text": "✏️ Редактировать", "callback_data": f"edit_{post_id}"},
                    {"text": "❌ Отклонить", "callback_data": f"reject_{post_id}"}
                ]
            ]
        }
        
        await self.bot.send_message(
            chat_id,
            message_text,
            reply_markup=markup
        )
    
    async def _publish_post(self, chat_id: int, post_id: str, post: PendingPost):
        article = post.article
        message_text = f"<b>{article.title}</b>\n{article.summary}\n\n<a href='{article.link}'>Источник</a>"
        
        if await self.bot.send_message(config.CHANNEL_ID, message_text):
            db.add_article(article)
            del self.bot.pending_posts[chat_id][post_id]
            await self.bot.send_message(chat_id, "Пост опубликован!")
        else:
            await self.bot.send_message(chat_id, "Ошибка публикации поста")
    
    async def fetch_news(self, chat_id: int):
        if chat_id not in config.ADMIN_IDS:
            await self.bot.send_message(chat_id, "У вас нет прав на эту команду")
            return
        
        await self.bot.send_message(chat_id, "Ищу свежие новости...")
        
        articles = await self.rss_processor.fetch_latest_articles(limit=config.MAX_POSTS_PER_REQUEST)
        
        if not articles:
            await self.bot.send_message(chat_id, "Нет новых новостей для обработки")
            return
        
        for article in articles:
            article.title, article.summary = await self.openrouter.summarize_article(article.link)
            post_id = f"{chat_id}_{hash(article.link)}"
            self.bot.pending_posts.setdefault(chat_id, {})[post_id] = PendingPost(article)
            await self._show_post_for_review(chat_id, post_id, self.bot.pending_posts[chat_id][post_id])
    
    async def post_latest_news(self, chat_id: int):
        if chat_id not in config.ADMIN_IDS:
            await self.bot.send_message(chat_id, "У вас нет прав на эту команду")
            return
        
        articles = await self.rss_processor.fetch_latest_articles(limit=1)
        
        if not articles:
            await self.bot.send_message(chat_id, "Нет новых новостей")
            return
        
        article = articles[0]
        article.title, article.summary = await self.openrouter.summarize_article(article.link)
        
        message_text = f"<b>{article.title}</b>\n{article.summary}\n\n<a href='{article.link}'>Источник</a>"
        
        if await self.bot.send_message(config.CHANNEL_ID, message_text):
            db.add_article(article)
            await self.bot.send_message(chat_id, "Новость опубликована!")
        else:
            await self.bot.send_message(chat_id, "Ошибка публикации новости")
    
    async def show_feedcache(self, chat_id: int):
        articles = db.get_all_articles()
        
        if not articles:
            await self.bot.send_message(chat_id, "База данных новостей пуста")
            return
        
        if len(str(articles)) < 3000:
            await self.bot.send_message(
                chat_id,
                f"Последние новости:\n{json.dumps(articles, ensure_ascii=False, indent=2)}"
            )
        else:
            with open("feedcache_dump.json", "w") as f:
                json.dump(articles, f, ensure_ascii=False, indent=2)
            
            await self.bot.send_message(chat_id, "Файл с данными:")
            # Здесь нужно добавить отправку файла (реализация зависит от вашего фреймворка)
    
    async def clear_feedcache(self, chat_id: int):
        count = db.clear_all_articles()
        await self.bot.send_message(chat_id, f"База данных очищена. Удалено записей: {count}")
    
    async def show_stats(self, chat_id: int):
        articles = db.get_all_articles()
        sources = {}
        
        for article in articles:
            sources[article["source"]] = sources.get(article["source"], 0) + 1
        
        stats_text = "📊 Статистика бота:\n"
        stats_text += f"• Всего новостей: {len(articles)}\n"
        stats_text += "• По источникам:\n"
        
        for source, count in sources.items():
            stats_text += f"  - {source}: {count}\n"
        
        stats_text += f"• Ожидают проверки: {sum(len(v) for v in self.bot.pending_posts.values())}"
        
        await self.bot.send_message(chat_id, stats_text)
    
    async def show_help(self, chat_id: int):
        help_text = """
📝 Доступные команды:
/fetch - Найти новые новости (только для админов)
/post - Опубликовать последнюю новость (только для админов)
/feedcache - Показать историю публикаций
/stats - Показать статистику
/help - Показать это сообщение
"""
        await self.bot.send_message(chat_id, help_text)
    
    async def run(self):
        # Здесь должна быть реализация вебхука или поллинга
        # Например, для Flask:
        from flask import Flask, request
        app = Flask(__name__)
        
        @app.route('/webhook', methods=['POST'])
        async def webhook():
            update = request.get_json()
            await self.handle_update(update)
            return "OK", 200
        
        app.run(host="0.0.0.0", port=5000)
    
    async def shutdown(self):
        await self.bot.close()
        await self.openrouter.close()

# ==================== Запуск приложения ====================
if __name__ == "__main__":
    app = NewsBotApplication()
    
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        asyncio.run(app.shutdown())
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        asyncio.run(app.shutdown())