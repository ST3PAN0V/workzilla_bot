import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, call, patch

from scripts.run_bot import configure_logging, generate_reply_for_order
from src.workzilla.analyzer import OrderDecision, normalize_order
from src.workzilla.runner import DecisionLog


class RunBotTest(unittest.TestCase):
    @patch("scripts.run_bot.logging.getLogger")
    @patch("scripts.run_bot.logging.basicConfig")
    def test_hides_http_client_urls_from_info_logs(
        self,
        basic_config,
        get_logger,
    ):
        configure_logging()

        basic_config.assert_called_once()
        self.assertEqual(
            get_logger.call_args_list,
            [call("httpx"), call("httpcore")],
        )
        self.assertEqual(
            get_logger.return_value.setLevel.call_args_list,
            [call(logging.WARNING), call(logging.WARNING)],
        )


class ReplyFlowTest(unittest.IsolatedAsyncioTestCase):
    @patch(
        "scripts.run_bot.generate_order_reply",
        new_callable=AsyncMock,
        return_value="Здравствуйте, Анна! Готов помочь 🎨",
    )
    async def test_loads_name_only_after_reply_button(self, generate_reply):
        class FakeClient:
            def __init__(self):
                self.customer_requests = []

            async def get_customer_name(self, customer_id):
                self.customer_requests.append(customer_id)
                return "Анна"

        client = FakeClient()
        decision = OrderDecision(
            order=normalize_order(
                {
                    "id": 7,
                    "subject": "Макет афиши",
                    "description": "Сделать яркую афишу",
                    "customerId": 99,
                }
            ),
            verdict="accept",
            reason="Подходящая задача",
        )

        with TemporaryDirectory() as temp_dir:
            decision_log = DecisionLog(Path(temp_dir) / "decisions.json")
            decision_log.append(decision)

            self.assertEqual(client.customer_requests, [])
            self.assertIsNone(decision_log.get_order("7").customer_name)

            first = await generate_reply_for_order("7", decision_log, client)
            second = await generate_reply_for_order("7", decision_log, client)
            restored = DecisionLog(decision_log.path)

        self.assertEqual(first, "Здравствуйте, Анна! Готов помочь 🎨")
        self.assertEqual(second, first)
        self.assertEqual(client.customer_requests, ["99"])
        generate_reply.assert_awaited_once()
        generated_order = generate_reply.await_args.args[0]
        self.assertEqual(generated_order.customer_name, "Анна")
        self.assertEqual(restored.get_order("7").customer_name, "Анна")
        self.assertEqual(restored.get_generated_reply("7"), first)
