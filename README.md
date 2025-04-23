# AutoNews

AutoNews — это Telegram-бот, который автоматически собирает новости из RSS-лент, генерирует краткие пересказы на русском языке с помощью ИИ (OpenAI) и публикует их в заданный Telegram-канал. Бот поддерживает управление настройками, администрирование и мониторинг через команды в Telegram.

## Основные функции

- **Автоматический парсинг новостей**: Собирает новости из популярных RSS-лент (The Verge, TechCrunch, Ars Technica и др.).
- **Генерация контента с помощью ИИ**: Использует OpenAI (например, модель `gpt-4o-mini`) для создания заголовков и кратких пересказов новостей на русском языке.
- **Публикация в Telegram**: Автоматически публикует новости в указанный канал с заданным интервалом.
- **Управление настройками**: Поддерживает настройку интервалов постинга, смену модели ИИ, редактирование промпта и управление администраторами.
- **Кэширование и фильтрация**: Использует SQLite для хранения кэша новостей и предотвращения дублирования.
- **Мониторинг и логирование**: Ведёт статистику постов, ошибок и дублей, отправляет уведомления об ошибках (опционально).
- **Резервное копирование**: Позволяет выгружать и загружать базу данных SQLite через Telegram.

## Требования

- Python 3.8+
- Библиотеки:
  ```bash
  pip install flask feedparser requests openai sqlite3
  ```
- Переменные окружения:
  - `TELEGRAM_TOKEN`: Токен вашего Telegram-бота.
  - `OPENAI_API_KEY`: Ключ API для OpenAI.
- Telegram-канал, где бот имеет права администратора.

## Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/goreforced/YCTNewsBot_TG.git
   cd AutoNews
   ```

2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Настройте переменные окружения:
   ```bash
   export TELEGRAM_TOKEN="your-telegram-bot-token"
   export OPENAI_API_KEY="your-openai-api-key"
   ```

4. Запустите приложение:
   ```bash
   python app.py
   ```

5. Настройте вебхук для Telegram:
   - Убедитесь, что ваш сервер доступен через HTTPS.
   - Отправьте запрос:
     ```bash
     curl -F "url=https://your-server.com/webhook" https://api.telegram.org/bot<your-telegram-token>/setWebhook
     ```

## Использование

1. Добавьте бота в Telegram-канал и сделайте его администратором.
2. Взаимодействуйте с ботом через команды в Telegram:

   **Основные команды**:
   - `/start` — Привязать канал или проверить доступ.
   - `/startposting` — Начать автоматический постинг.
   - `/stopposting` — Остановить постинг.
   - `/setinterval <time>.

   **Настройка**:
   - `/editprompt` — Изменить промпт для ИИ.
   - `/changellm <model>` — Сменить модель ИИ (например, `gpt-4o-mini`).
   - `/errnotification <on/off>` — Включить/выключить уведомления об ошибках.

   **Мониторинг**:
   - `/info` — Показать статус бота.
   - `/errinf` — Показать последние ошибки.
   - `/feedcache` — Показать кэш новостей.
   - `/feedcacheclear` — Очистить кэш.

   **Администрирование**:
   - `/addadmin <@username>` — Добавить администратора.
   - `/removeadmin <@username>` — Удалить администратора.
   - `/sqlitebackup` — Выгрузить базу данных.
   - `/sqliteupdate` — Загрузить базу данных.

   **Дополнительно**:
   - `/nextpost` — Сбросить таймер и запостить немедленно.
   - `/skiprss` — Пропустить следующий RSS-источник.
   - `/help` — Показать список команд.

## Структура базы данных

Бот использует SQLite (`feedcache.db`) для хранения данных. Основные таблицы:

- `feedcache`: Кэш новостей (ID, заголовок, пересказ, ссылка, источник, время).
- `channels`: Информация о каналах (ID канала, создатель).
- `admins`: Список администраторов канала.
- `config`: Настройки (промпт, модель ИИ, уведомления об ошибках).
- `errors`: Лог ошибок (время, сообщение, ссылка).

## Логирование

- Логи выводятся в консоль в формате: `%(asctime)s - %(levelname)s - %(message)s`.
- Уровень логирования: `INFO`.

## Ограничения

- Бот работает только с публичными RSS-лентами.
- Для генерации контента требуется действующий ключ OpenAI API.
- Telegram ограничивает длину сообщений до 4096 символов, поэтому длинные пересказы обрезаются.
- Бот должен быть администратором в целевом канале.

## Лицензия

GPL-3.0 License. См. файл `LICENSE` для подробностей.

## Контакты

Если у вас есть вопросы или предложения, создайте issue в репозитории.

# English 
# AutoNews

AutoNews is a Telegram bot that automatically collects news from RSS feeds, generates concise summaries in Russian using AI (OpenAI), and posts them to a specified Telegram channel. The bot supports configuration management, administration, and monitoring through Telegram commands.

## Key Features

- **Automated News Parsing**: Fetches news from popular RSS feeds (The Verge, TechCrunch, Ars Technica, etc.).
- **AI-Generated Content**: Uses OpenAI (e.g., `gpt-4o-mini` model) to create headlines and brief news summaries in Russian.
- **Telegram Posting**: Automatically posts news to a designated channel at set intervals.
- **Configuration Management**: Allows customization of posting intervals, AI model selection, prompt editing, and admin management.
- **Caching and Filtering**: Uses SQLite to store a news cache and prevent duplicates.
- **Monitoring and Logging**: Tracks post counts, errors, and duplicates, with optional error notifications.
- **Database Backup**: Supports exporting and importing the SQLite database via Telegram.

## Requirements

- Python 3.8+
- Dependencies:
  ```bash
  pip install flask feedparser requests openai sqlite3
  ```
- Environment Variables:
  - `TELEGRAM_TOKEN`: Your Telegram bot token.
  - `OPENAI_API_KEY`: Your OpenAI API key.
- A Telegram channel where the bot has admin privileges.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/goreforced/YCTNewsBot_TG.git
   cd AutoNews
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export TELEGRAM_TOKEN="your-telegram-bot-token"
   export OPENAI_API_KEY="your-openai-api-key"
   ```

4. Run the application:
   ```bash
   python app.py
   ```

5. Set up a Telegram webhook:
   - Ensure your server is accessible via HTTPS.
   - Send the request:
     ```bash
     curl -F "url=https://your-server.com/webhook" https://api.telegram.org/bot<your-telegram-token>/setWebhook
     ```

## Usage

1. Add the bot to a Telegram channel and grant it admin privileges.
2. Interact with the bot using Telegram commands:

   **Core Commands**:
   - `/start` — Bind a channel or check access.
   - `/startposting` — Start automatic posting.
   - `/stopposting` — Stop posting.
   - `/setinterval <time>` — Set posting interval (e.g., `34m`, `1h`, `2h 53m`).

   **Configuration**:
   - `/editprompt` — Edit the AI prompt.
   - `/changellm <model>` — Switch AI model (e.g., `gpt-4o-mini`).
   - `/errnotification <on/off>` — Enable/disable error notifications.

   **Monitoring**:
   - `/info` — Show bot status.
   - `/errinf` — Display recent errors.
   - `/feedcache` — Show news cache.
   - `/feedcacheclear` — Clear the cache.

   **Administration**:
   - `/addadmin <@username>` — Add an admin.
   - `/removeadmin <@username>` — Remove an admin.
   - `/sqlitebackup` — Export the SQLite database.
   - `/sqliteupdate` — Import the SQLite database.

   **Additional**:
   - `/nextpost` — Reset the timer and post immediately.
   - `/skiprss` — Skip the next RSS feed.
   - `/help` — Show the command list.

## Database Structure

The bot uses SQLite (`feedcache.db`) to store data. Main tables:

- `feedcache`: News cache (ID, title, summary, link, source, timestamp).
- `channels`: Channel information (channel ID, creator).
- `admins`: List of channel admins.
- `config`: Settings (AI prompt, model, error notifications).
- `errors`: Error log (timestamp, message, link).

## Logging

- Logs are output to the console in the format: `%(asctime)s - %(levelname)s - %(message)s`.
- Logging level: `INFO`.

## Limitations

- The bot only works with public RSS feeds.
- A valid OpenAI API key is required for content generation.
- Telegram limits message length to 4096 characters, so long summaries are truncated.
- The bot must be an admin in the target channel.

## License

GPL-3.0 License. See the `LICENSE` file for details.

## Contact

For questions or suggestions, create an issue in the repository.