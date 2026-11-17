# Workzilla Bot

A Python service that monitors Workzilla orders, classifies them with YandexGPT, and sends relevant opportunities to Telegram. A reply button generates a Russian response for the selected order.

## What it does

- Polls open orders through an asynchronous HTTP client.
- Classifies new orders using the project's matching criteria and LLM prompts.
- Keeps a local decision log to avoid analyzing the same order again.
- Sends accepted orders to one configured Telegram recipient.
- Generates a reply on request, retrieves the customer's name when available, and reuses previously generated replies.
- Retries pending notifications after a delivery failure.

## Stack

Python 3.10+, `asyncio`, `httpx`, `python-dotenv`, Yandex AI Studio, and Telegram Bot API. Runtime state is stored in local JSON files.

## Requirements

- Python 3.10 or newer.
- A Workzilla account with access to orders and its email inbox.
- A Telegram bot created through BotFather.
- A Yandex Cloud API key and folder ID with access to the configured model.

## Setup

Run the following from a terminal on Linux:

```bash
git clone https://github.com/ST3PAN0V/workzilla_bot.git
cd workzilla_bot
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Set your own values in `.env`:

```dotenv
YC_API_KEY=<your-api-key>
YC_FOLDER_ID=<your-folder-id>
YC_MODEL=yandexgpt-5-lite
WORKZILLA_EMAIL=<your-workzilla-email>
WORKZILLA_BASE_URL=https://client.work-zilla.com
WORKZILLA_POLL_INTERVAL_SECONDS=10
TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
```

The model shown above is the client's current default. See [the LLM integration notes](docs/YANDEX_LLM.md) for model URI and endpoint options.

### Choose the Telegram recipient

The bot currently serves a single recipient, configured in source code. Set `RECIPIENT_USERNAME` in [`src/workzilla/telegram.py`](src/workzilla/telegram.py) to the intended Telegram username, without `@`.

The optional Telegram smoke test has a separate `RECIPIENT_USERNAME` in [`scripts/telegram_smoke.py`](scripts/telegram_smoke.py). Configure it separately if you use that test.

## Run

First, authenticate with Workzilla. The script reuses a saved session or asks for the one-time code sent by email:

```bash
.venv/bin/python -m scripts.workzilla_smoke
```

Start the bot:

```bash
.venv/bin/python -m scripts.run_bot
```

Send `/start` to the Telegram bot from the configured recipient account. Once registered, the recipient is saved locally.

The service polls for new orders, sends matching orders to Telegram, and handles the reply button. Generated replies are delivered in Telegram for review.

## Tests

Run the repository's unittest suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

### Optional live integration check

The Telegram smoke script fetches an order from the Design category, generates a reply, and sends both to its configured recipient:

```bash
.venv/bin/python -m scripts.telegram_smoke
```

This check uses live Workzilla, LLM, and Telegram APIs. The configured recipient must first send `/start`. Stop the main bot before running it, because both processes poll Telegram updates using the same token.

## Run as a Linux service

A systemd unit is included in [`deploy/workzilla-bot.service`](deploy/workzilla-bot.service). Before installing it, adapt `User`, `Group`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` to your account and installation directory.

Complete the interactive authentication and recipient registration first, then install the customized unit:

```bash
sudo cp deploy/workzilla-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workzilla-bot
sudo systemctl status workzilla-bot
```

View logs with:

```bash
sudo journalctl -u workzilla-bot -f
```

If the Workzilla session expires, stop the service, run `scripts.workzilla_smoke` interactively from the project directory, and start the service again.

## Project layout

| Path | Purpose |
| --- | --- |
| [`src/workzilla/client.py`](src/workzilla/client.py) | Workzilla authentication and API requests |
| [`src/workzilla/analyzer.py`](src/workzilla/analyzer.py) | Order normalization and classification |
| [`src/workzilla/runner.py`](src/workzilla/runner.py) | Polling, decisions, and notification retries |
| [`src/workzilla/responder.py`](src/workzilla/responder.py) | Reply generation |
| [`src/workzilla/telegram.py`](src/workzilla/telegram.py) | Telegram delivery and callbacks |
| [`shared_llm/`](shared_llm/) | Shared Yandex LLM client |
| [`scripts/`](scripts/) | Entry points and integration checks |
| [`tests/`](tests/) | Automated tests |
| `data/` | Local session, recipient, and decision state |

`.env` and runtime files under `data/` are excluded by `.gitignore`. Matching prompts and recipient configuration are specific to this project's workflow; review them before adapting the bot to another use case.

