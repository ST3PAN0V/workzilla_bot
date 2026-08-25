# Workzilla bot

Бот опрашивает открытые заказы Workzilla, классифицирует их через YandexGPT и
присылает подходящие заказы в Telegram. По кнопке «Ответить» получает имя
заказчика и генерирует готовый русский отклик.

## Требования

- Python 3.10+;
- аккаунт Workzilla с доступом к заказам;
- Telegram-бот от BotFather;
- API-ключ и каталог Yandex Cloud для AI Studio.

## Установка

```bash
git clone https://github.com/ST3PAN0V/workzilla_bot.git
cd workzilla_bot
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
chmod 600 .env
```

Заполните `.env`:

```dotenv
YC_API_KEY=...
YC_FOLDER_ID=...
YC_MODEL=yandexgpt-5-lite
WORKZILLA_EMAIL=...
WORKZILLA_BASE_URL=https://client.work-zilla.com
WORKZILLA_POLL_INTERVAL_SECONDS=10
TELEGRAM_BOT_TOKEN=...
```

Секреты, сессии и журнал заказов хранятся только локально в `.env` и `data/` и
не попадают в Git.

## Первый запуск

Сначала авторизуйте Workzilla одноразовым кодом из письма:

```bash
.venv/bin/python -m scripts.workzilla_smoke
```

Затем запустите бота и отправьте Telegram-боту `/start` от аккаунта
`@vandoshka`:

```bash
.venv/bin/python -m scripts.run_bot
```

Smoke-тест берёт первый заказ из раздела «Дизайн», генерирует отклик и отправляет
заказ с ответом пользователю `@ArtemS101`:

```bash
.venv/bin/python -m scripts.telegram_smoke
```

Перед первым smoke-тестом `@ArtemS101` должен отправить Telegram-боту `/start`.
Не запускайте одновременно основной бот и smoke-тест: Telegram допускает только
один процесс `getUpdates` для одного токена.

## Тесты

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Сервер

Подключение:

```bash
ssh -l st3pan0v 158.160.63.154
```

Рабочий каталог — `/home/st3pan0v/apps/workzilla_bot`. После клонирования,
установки и первой ручной авторизации установите systemd-сервис:

```bash
sudo cp deploy/workzilla-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workzilla-bot
sudo systemctl status workzilla-bot
```

Логи:

```bash
sudo journalctl -u workzilla-bot -f
```

Обновление:

```bash
cd /home/st3pan0v/apps/workzilla_bot
git pull --ff-only
.venv/bin/pip install -e .
sudo systemctl restart workzilla-bot
```

Если сессия Workzilla истекла, остановите сервис, заново выполните
`scripts.workzilla_smoke` в терминале и запустите сервис снова.
