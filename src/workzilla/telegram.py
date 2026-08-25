import asyncio
import html
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from src.workzilla.analyzer import OrderData


TELEGRAM_API_BASE_URL = "https://api.telegram.org"
RECIPIENT_USERNAME = "vandoshka"
DEFAULT_CHAT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "telegram_recipient.json"
)
WORKZILLA_ORDER_URL = "https://client.work-zilla.com/freelancer/{order_id}"
DESCRIPTION_LIMIT = 200
MESSAGE_LIMIT = 4096
REPLY_CALLBACK_PREFIX = "reply:"

logger = logging.getLogger(__name__)

ReplyHandler = Callable[[str], Awaitable[str]]


class TelegramError(RuntimeError):
    """Telegram request or response failed."""


class TelegramConfigurationError(TelegramError):
    """Telegram configuration is missing or invalid."""


def truncate_description(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def format_price(price: int | float | None) -> str:
    if price is None:
        return "Не указана"
    value = float(price)
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ") + " ₽"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def build_order_message(order: OrderData) -> str:
    title = " ".join(order.title.split()) or "Без названия"
    description = truncate_description(order.description)
    if not description:
        description = "Описание не указано"
    url = WORKZILLA_ORDER_URL.format(order_id=order.order_id)
    return (
        "✅ Подходящий заказ Workzilla\n\n"
        f"📌 {title}\n\n"
        f"💰 Цена: {format_price(order.price)}\n\n"
        f"📝 Описание:\n{description}\n\n"
        f"🔗 Открыть заказ:\n{url}"
    )


class TelegramNotifier:
    """Register one Telegram recipient and send suitable Workzilla orders."""

    def __init__(
        self,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        chat_path: str | Path = DEFAULT_CHAT_PATH,
        reply_handler: ReplyHandler | None = None,
        recipient_username: str = RECIPIENT_USERNAME,
    ) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not self.token:
            raise TelegramConfigurationError(
                "Environment variable TELEGRAM_BOT_TOKEN is required"
            )
        self.chat_path = Path(chat_path)
        self.recipient_username = recipient_username.removeprefix("@").lower()
        if not self.recipient_username:
            raise TelegramConfigurationError(
                "Telegram recipient username is required"
            )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=40)
        self._chat_id = self._load_chat_id()
        self._reply_handler = reply_handler

    async def __aenter__(self) -> "TelegramNotifier":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def wait_for_recipient(self) -> None:
        """Wait for the configured recipient's /start and save the chat id."""
        await self._call("getMe", {})
        if self._chat_id is not None:
            return

        offset = 0
        while self._chat_id is None:
            try:
                updates = await self._call(
                    "getUpdates",
                    {
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": ["message"],
                    },
                )
            except TelegramError as error:
                logger.warning("Telegram polling failed: %s", error)
                await asyncio.sleep(5)
                continue
            if not isinstance(updates, list):
                raise TelegramError("Telegram returned invalid updates")

            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                message = update.get("message")
                if self._is_recipient_start(message):
                    chat_id = message["chat"]["id"]
                    self._save_chat_id(chat_id)
                    self._chat_id = chat_id
                    await self.send_message("Уведомления Workzilla подключены")
                    return

    async def send_order(self, order: OrderData) -> None:
        reply_markup = None
        if self._reply_handler is not None:
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Ответить",
                            "callback_data": (
                                REPLY_CALLBACK_PREFIX + order.order_id
                            ),
                        }
                    ]
                ]
            }
        await self.send_message(
            build_order_message(order),
            reply_markup=reply_markup,
        )

    async def send_message(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        if self._chat_id is None:
            raise TelegramConfigurationError(
                "Telegram recipient is not registered"
            )
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._call("sendMessage", payload)

    async def run_reply_callbacks(self) -> None:
        """Poll Telegram and process Reply button presses forever."""
        if self._reply_handler is None:
            raise TelegramConfigurationError("Reply handler is not configured")

        offset = 0
        while True:
            try:
                updates = await self._call(
                    "getUpdates",
                    {
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": ["callback_query"],
                    },
                )
                if not isinstance(updates, list):
                    raise TelegramError("Telegram returned invalid updates")
                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = max(offset, update_id + 1)
                    callback = update.get("callback_query")
                    if isinstance(callback, dict):
                        await self._handle_reply_callback(callback)
            except TelegramError as error:
                logger.warning("Telegram callback polling failed: %s", error)
                await asyncio.sleep(5)

    async def _handle_reply_callback(self, callback: dict[str, Any]) -> None:
        if self._reply_handler is None or not self._is_recipient_callback(callback):
            return

        callback_id = callback["id"]
        data = callback["data"]
        message = callback["message"]
        order_id = data.removeprefix(REPLY_CALLBACK_PREFIX)
        await self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Генерирую ответ…"},
        )

        try:
            reply = (await self._reply_handler(order_id)).strip()
        except Exception as error:
            logger.error(
                "Could not generate reply for order %s: %s",
                order_id,
                type(error).__name__,
            )
            return
        if not reply:
            logger.error("Generated an empty reply for order %s", order_id)
            return

        original_text = message.get("text", "")
        suffix = "\n\n✍️ Ответ:\n"
        available = MESSAGE_LIMIT - len(original_text) - len(suffix)
        if available <= 0:
            logger.error("Telegram message is too long for order %s", order_id)
            return
        edited_text = (
            html.escape(original_text)
            + suffix
            + "<pre>"
            + html.escape(reply[:available])
            + "</pre>"
        )
        await self._call(
            "editMessageText",
            {
                "chat_id": self._chat_id,
                "message_id": message["message_id"],
                "text": edited_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": []},
            },
        )

    def _is_recipient_callback(self, callback: object) -> bool:
        if not isinstance(callback, dict):
            return False
        sender = callback.get("from")
        message = callback.get("message")
        data = callback.get("data")
        callback_id = callback.get("id")
        if not isinstance(sender, dict) or not isinstance(message, dict):
            return False
        chat = message.get("chat")
        return (
            isinstance(chat, dict)
            and chat.get("id") == self._chat_id
            and isinstance(message.get("message_id"), int)
            and isinstance(message.get("text"), str)
            and isinstance(sender.get("username"), str)
            and sender["username"].lower() == self.recipient_username
            and isinstance(callback_id, str)
            and isinstance(data, str)
            and data.startswith(REPLY_CALLBACK_PREFIX)
            and bool(data.removeprefix(REPLY_CALLBACK_PREFIX))
        )

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{TELEGRAM_API_BASE_URL}/bot{self.token}/{method}"
        try:
            response = await self._client.post(url, json=payload)
        except httpx.HTTPError as error:
            raise TelegramError(
                f"Could not connect to Telegram for {method}"
            ) from error

        try:
            data = response.json()
        except ValueError as error:
            raise TelegramError("Telegram returned invalid JSON") from error

        if not isinstance(data, dict):
            raise TelegramError("Telegram returned an unexpected response")
        if response.status_code >= 400 or data.get("ok") is not True:
            description = data.get("description")
            if not isinstance(description, str):
                description = "unknown error"
            raise TelegramError(
                f"Telegram rejected {method}: {description[:200]}"
            )
        return data.get("result")

    def _is_recipient_start(self, message: object) -> bool:
        if not isinstance(message, dict):
            return False
        sender = message.get("from")
        chat = message.get("chat")
        text = message.get("text")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            return False
        username = sender.get("username")
        chat_id = chat.get("id")
        chat_type = chat.get("type")
        command = text.split(maxsplit=1)[0] if isinstance(text, str) else ""
        return (
            isinstance(username, str)
            and username.lower() == self.recipient_username
            and isinstance(chat_id, int)
            and chat_type == "private"
            and command.split("@", 1)[0] == "/start"
        )

    def _load_chat_id(self) -> int | None:
        if not self.chat_path.exists():
            return None
        try:
            data = json.loads(self.chat_path.read_text(encoding="utf-8"))
            chat_id = data["chat_id"]
            username = data["username"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise TelegramConfigurationError(
                f"Invalid Telegram recipient file: {self.chat_path}"
            ) from error
        if not isinstance(chat_id, int) or username != self.recipient_username:
            raise TelegramConfigurationError(
                f"Invalid Telegram recipient file: {self.chat_path}"
            )
        return chat_id

    def _save_chat_id(self, chat_id: int) -> None:
        try:
            self.chat_path.parent.mkdir(parents=True, exist_ok=True)
            self.chat_path.write_text(
                json.dumps(
                    {"username": self.recipient_username, "chat_id": chat_id},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.chat_path.chmod(0o600)
        except OSError as error:
            raise TelegramConfigurationError(
                f"Could not save Telegram recipient to {self.chat_path}"
            ) from error
