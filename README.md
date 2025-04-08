# TChNewsBot

## Описание (Русский)
TChNewsBot — это Telegram-бот, который автоматически собирает новости из RSS-лент, генерирует краткие пересказы на русском языке с помощью ИИ (OpenRouter API) и публикует их в заданный Telegram-канал. Бот поддерживает управление через команды, кэширование новостей в SQLite и гибкую настройку. Этот проект частично разработан при поддержке Grok, созданного xAI, который помог с кодом и документацией.

### Возможности
- **Парсинг RSS-лент**: Собирает новости из популярных источников (The Verge, TechCrunch, 9to5Google и др.).
- **Генерация новостей**: Создаёт заголовки и пересказы на русском языке с использованием OpenRouter API.
- **Проверка языка**: Фильтрует заголовки, оставляя только латиницу и кириллицу, с автоматической перегенерацией при необходимости.
- **Гибкие интервалы**: Позволяет задавать интервал постинга (например, `34m`, `1h 30m`).
- **Управление ИИ**: Поддерживает смену модели (например, `xai/xai-grok`) и редактирование промпта через команды.
- **Администрирование**: Управление доступом с поддержкой нескольких администраторов канала.
- **Кэширование**: Сохраняет новости в SQLite, избегая дублей.
- **Логирование**: Детализированные логи для отладки и мониторинга.
- **Команды управления**: Включают запуск/остановку постинга, просмотр статуса, резервное копирование базы и многое другое.

### Требования
- Python 3.8 или выше
- SQLite для кэширования новостей
- Зависимости Python:
  - `flask`
  - `feedparser`
  - `requests`

### Лицензия
Проект распространяется под лицензией [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0). Используйте, улучшайте и делитесь — это крутая тема!

---

## Description (English)
TChNewsBot is a Telegram bot that automatically fetches news from RSS feeds, generates concise summaries in Russian using AI (OpenRouter API), and posts them to a specified Telegram channel. The bot offers command-based control, news caching in SQLite, and flexible customization. This project was partially developed with the assistance of Grok, created by xAI, which contributed to the code and documentation.

### Features
- **RSS Parsing**: Gathers news from popular sources (The Verge, TechCrunch, 9to5Google, etc.).
- **News Generation**: Creates headlines and summaries in Russian using OpenRouter API.
- **Language Check**: Filters headlines to allow only Latin and Cyrillic characters, with automatic regeneration if needed.
- **Flexible Intervals**: Customizable posting intervals (e.g., `34m`, `1h 30m`).
- **AI Management**: Supports switching models (e.g., `xai/xai-grok`) and editing prompts via commands.
- **Administration**: Multi-admin support for channel management.
- **Caching**: Stores news in SQLite to prevent duplicates.
- **Logging**: Detailed logs for debugging and monitoring.
- **Control Commands**: Includes start/stop posting, status checks, database backups, and more.

### Requirements
- Python 3.8 or higher
- SQLite for news caching
- Python dependencies:
  - `flask`
  - `feedparser`
  - `requests`

### License
The project is licensed under the [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0). Use it, improve it, and share it — it’s awesome stuff!