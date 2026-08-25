import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx

from src.workzilla.analyzer import OrderData
from src.workzilla.telegram import (
    TelegramConfigurationError,
    TelegramNotifier,
    build_order_message,
    format_price,
    truncate_description,
)


class TelegramNotifierTest(unittest.IsolatedAsyncioTestCase):
    def test_truncates_description_to_two_hundred_characters(self):
        description = "слово " * 50

        result = truncate_description(description)

        self.assertEqual(len(result), 200)
        self.assertTrue(result.endswith("..."))

    def test_builds_message_with_workzilla_link(self):
        order = OrderData(
            order_id="22132503",
            title="Оформление канала",
            description="Сделать статичные обложки",
            price=17000.0,
            customer_name="Анна",
        )

        message = build_order_message(order)

        self.assertIn("Оформление канала", message)
        self.assertIn("Сделать статичные обложки", message)
        self.assertIn("17 000 ₽", message)
        self.assertNotIn("Заказчик:", message)
        self.assertIn(
            "https://client.work-zilla.com/freelancer/22132503",
            message,
        )

    def test_formats_price(self):
        self.assertEqual(format_price(500.0), "500 ₽")
        self.assertEqual(format_price(1234.5), "1 234,50 ₽")
        self.assertEqual(format_price(None), "Не указана")

    async def test_does_not_register_group_chat(self):
        message = {
            "text": "/start",
            "from": {"username": "vandoshka"},
            "chat": {"id": -100123, "type": "group"},
        }
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"ok": True, "result": {}},
                )
            )
        )
        with TemporaryDirectory() as temp_dir:
            notifier = TelegramNotifier(
                token="test-token",
                client=http_client,
                chat_path=Path(temp_dir) / "recipient.json",
            )

            self.assertFalse(notifier._is_recipient_start(message))

        await http_client.aclose()

    async def test_registers_vandoshka_and_sends_order(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/getUpdates"):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": [
                            {
                                "update_id": 10,
                                "message": {
                                    "text": "/start",
                                    "from": {"username": "vandoshka"},
                                    "chat": {"id": 12345, "type": "private"},
                                },
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"ok": True, "result": {}})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with TemporaryDirectory() as temp_dir:
            chat_path = Path(temp_dir) / "recipient.json"
            notifier = TelegramNotifier(
                token="test-token",
                client=http_client,
                chat_path=chat_path,
            )
            await notifier.wait_for_recipient()
            await notifier.send_order(
                OrderData("7", "Новый заказ", "Короткое описание")
            )

            stored = json.loads(chat_path.read_text(encoding="utf-8"))
            mode = chat_path.stat().st_mode & 0o777

        await http_client.aclose()

        self.assertEqual(
            stored,
            {"username": "vandoshka", "chat_id": 12345},
        )
        self.assertEqual(mode, 0o600)
        send_requests = [
            request
            for request in requests
            if request.url.path.endswith("/sendMessage")
        ]
        self.assertEqual(len(send_requests), 2)
        order_payload = json.loads(send_requests[-1].content)
        self.assertEqual(order_payload["chat_id"], 12345)
        self.assertIn("/freelancer/7", order_payload["text"])

    async def test_registers_configured_smoke_recipient(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/getUpdates"):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": [
                            {
                                "update_id": 10,
                                "message": {
                                    "text": "/start",
                                    "from": {"username": "ArtemS101"},
                                    "chat": {"id": 54321, "type": "private"},
                                },
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"ok": True, "result": {}})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with TemporaryDirectory() as temp_dir:
            chat_path = Path(temp_dir) / "recipient.json"
            notifier = TelegramNotifier(
                token="test-token",
                client=http_client,
                chat_path=chat_path,
                recipient_username="@ArtemS101",
            )
            await notifier.wait_for_recipient()
            stored = json.loads(chat_path.read_text(encoding="utf-8"))

        await http_client.aclose()

        self.assertEqual(
            stored,
            {"username": "artems101", "chat_id": 54321},
        )

    async def test_reply_button_edits_original_message(self):
        requests: list[httpx.Request] = []
        handled_orders: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": {}})

        async def reply_handler(order_id: str) -> str:
            handled_orders.append(order_id)
            return "Здравствуйте! Готова сделать <макет> & проверить."

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with TemporaryDirectory() as temp_dir:
            chat_path = Path(temp_dir) / "recipient.json"
            chat_path.write_text(
                json.dumps({"username": "vandoshka", "chat_id": 12345}),
                encoding="utf-8",
            )
            notifier = TelegramNotifier(
                token="test-token",
                client=http_client,
                chat_path=chat_path,
                reply_handler=reply_handler,
            )
            order = OrderData("7", "Новый <заказ>", "Описание", 500.0)
            original_text = build_order_message(order)
            await notifier.send_order(order)
            await notifier._handle_reply_callback(
                {
                    "id": "callback-1",
                    "data": "reply:7",
                    "from": {"username": "vandoshka"},
                    "message": {
                        "message_id": 99,
                        "text": original_text,
                        "chat": {"id": 12345},
                    },
                }
            )

        await http_client.aclose()

        self.assertEqual(handled_orders, ["7"])
        payloads = {
            request.url.path.rsplit("/", 1)[-1]: json.loads(request.content)
            for request in requests
        }
        button = payloads["sendMessage"]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button, {"text": "Ответить", "callback_data": "reply:7"})
        edited = payloads["editMessageText"]
        self.assertEqual(edited["message_id"], 99)
        self.assertIn("✍️ Ответ:\n<pre>Здравствуйте!", edited["text"])
        self.assertIn("Новый &lt;заказ&gt;", edited["text"])
        self.assertIn("&lt;макет&gt; &amp; проверить", edited["text"])
        self.assertIn("</pre>", edited["text"])
        self.assertEqual(edited["parse_mode"], "HTML")
        self.assertEqual(edited["reply_markup"], {"inline_keyboard": []})

    @patch("src.workzilla.telegram.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_transient_error_while_waiting_for_start(self, sleep):
        update_attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal update_attempts
            if request.url.path.endswith("/getMe"):
                return httpx.Response(200, json={"ok": True, "result": {}})
            if request.url.path.endswith("/getUpdates"):
                update_attempts += 1
                if update_attempts == 1:
                    raise httpx.ConnectTimeout("temporary timeout")
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": [
                            {
                                "update_id": 10,
                                "message": {
                                    "text": "/start",
                                    "from": {"username": "vandoshka"},
                                    "chat": {"id": 12345, "type": "private"},
                                },
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"ok": True, "result": {}})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with TemporaryDirectory() as temp_dir:
            notifier = TelegramNotifier(
                token="test-token",
                client=http_client,
                chat_path=Path(temp_dir) / "recipient.json",
            )
            await notifier.wait_for_recipient()

        await http_client.aclose()

        self.assertEqual(update_attempts, 2)
        sleep.assert_awaited_once_with(5)

    @patch.dict(os.environ, {}, clear=True)
    def test_requires_token(self):
        with self.assertRaises(TelegramConfigurationError):
            TelegramNotifier()
