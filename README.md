# Workzilla Bot

Сервис на Python для мониторинга заказов Workzilla: классифицирует задания с помощью YandexGPT и отправляет подходящие предложения в Telegram. По кнопке готовит ответ на русском языке для выбранного заказа.

**Стек:** Python 3.10+ · asyncio · httpx · python-dotenv · Yandex AI Studio · Telegram Bot API

## Возможности

- Получение открытых заказов через асинхронный HTTP-клиент.
- Классификация новых заданий по критериям и LLM-промптам проекта.
- Локальный журнал решений, который помогает не анализировать один заказ повторно.
- Отправка подходящих заказов одному настроенному получателю в Telegram.
- Генерация ответа по запросу: с именем заказчика, если оно доступно, и повторным использованием ранее подготовленного текста.
- Повторная отправка уведомлений, которые не удалось доставить.

Состояние сервиса хранится в локальных JSON-файлах.

## Что нужно для запуска

- Python 3.10 или новее.
- Аккаунт Workzilla с доступом к заказам и связанной электронной почте.
- Telegram-бот, созданный через BotFather.
- API-ключ Yandex Cloud и идентификатор каталога с доступом к выбранной модели.

## Установка и настройка

Выполните в терминале Linux:

```bash
git clone https://github.com/ST3PAN0V/workzilla_bot.git
cd workzilla_bot
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Укажите свои значения в `.env`:

```dotenv
YC_API_KEY=<your-api-key>
YC_FOLDER_ID=<your-folder-id>
YC_MODEL=yandexgpt-5-lite
WORKZILLA_EMAIL=<your-workzilla-email>
WORKZILLA_BASE_URL=https://client.work-zilla.com
WORKZILLA_POLL_INTERVAL_SECONDS=10
TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
```

В примере указана модель, которую клиент использует по умолчанию. Варианты URI модели и API-адресов описаны в [документации LLM-интеграции](docs/YANDEX_LLM.md).

### Получатель в Telegram

Текущая реализация работает с одним получателем, который задаётся в исходном коде. В [`src/workzilla/telegram.py`](src/workzilla/telegram.py) установите `RECIPIENT_USERNAME`: имя пользователя Telegram без `@`.

У необязательной интеграционной проверки есть отдельный `RECIPIENT_USERNAME` в [`scripts/telegram_smoke.py`](scripts/telegram_smoke.py). Если будете запускать этот скрипт, настройте и его.

## Запуск

Сначала авторизуйтесь в Workzilla. Скрипт использует сохранённую сессию или запрашивает одноразовый код из письма:

```bash
.venv/bin/python -m scripts.workzilla_smoke
```

Затем запустите бота:

```bash
.venv/bin/python -m scripts.run_bot
```

Отправьте боту `/start` с аккаунта настроенного получателя. После регистрации данные получателя сохраняются локально.

Сервис начнёт опрашивать новые заказы, отправлять подходящие предложения и обрабатывать кнопку ответа. Подготовленные ответы приходят в Telegram для просмотра.

## Проверки

### Автоматические тесты

Запуск набора тестов на `unittest`:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

### Необязательная проверка интеграций

Скрипт получает заказ из категории «Дизайн», генерирует ответ и отправляет оба сообщения своему получателю:

```bash
.venv/bin/python -m scripts.telegram_smoke
```

Проверка обращается к реальным API Workzilla, LLM и Telegram. Получатель должен предварительно отправить `/start`. Перед проверкой остановите основной бот: оба процесса получают обновления Telegram с одним токеном.

## Запуск как службы Linux

В репозитории есть systemd-юнит [`deploy/workzilla-bot.service`](deploy/workzilla-bot.service). Перед установкой адаптируйте `User`, `Group`, `WorkingDirectory`, `EnvironmentFile` и `ExecStart` под свой аккаунт и каталог проекта.

Сначала выполните интерактивную авторизацию и регистрацию получателя, затем установите настроенный юнит:

```bash
sudo cp deploy/workzilla-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workzilla-bot
sudo systemctl status workzilla-bot
```

Просмотр журнала:

```bash
sudo journalctl -u workzilla-bot -f
```

Если сессия Workzilla истечёт, остановите службу, интерактивно запустите `scripts.workzilla_smoke` из каталога проекта и снова запустите службу.

## Структура проекта

| Путь | Назначение |
| --- | --- |
| [`src/workzilla/client.py`](src/workzilla/client.py) | Авторизация в Workzilla и запросы к API |
| [`src/workzilla/analyzer.py`](src/workzilla/analyzer.py) | Нормализация и классификация заказов |
| [`src/workzilla/runner.py`](src/workzilla/runner.py) | Опрос заказов, учёт решений и повторная отправка уведомлений |
| [`src/workzilla/responder.py`](src/workzilla/responder.py) | Генерация ответов |
| [`src/workzilla/telegram.py`](src/workzilla/telegram.py) | Отправка сообщений и обработка кнопок Telegram |
| [`shared_llm/`](shared_llm/) | Общий клиент Yandex LLM |
| [`scripts/`](scripts/) | Точки входа и проверки интеграций |
| [`tests/`](tests/) | Автоматические тесты |
| `data/` | Локальное состояние сессии, получателя и решений |

Файл `.env` и рабочие файлы в `data/` исключены через `.gitignore`. Промпты отбора и настройки получателя рассчитаны на сценарий этого проекта; перед адаптацией бота под свои задачи их нужно проверить.
