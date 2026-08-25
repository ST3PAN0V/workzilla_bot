import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shared_llm.client import LLMError

from src.workzilla.analyzer import OrderDecision, normalize_order
from src.workzilla.runner import DecisionLog, poll_interval_from_env, run_once
from src.workzilla.telegram import TelegramError


class FakeWorkzillaClient:
    def __init__(self, orders, customer_names=None):
        self.orders = orders
        self.customer_names = customer_names or {}
        self.customer_requests = []

    async def get_open_orders(self):
        return self.orders

    async def get_customer_name(self, customer_id):
        self.customer_requests.append(customer_id)
        return self.customer_names.get(customer_id)


async def accept_order(order):
    return OrderDecision(
        order=order,
        verdict="accept",
        reason="Подходящая задача по дизайну",
    )


async def reject_order(order):
    return OrderDecision(
        order=order,
        verdict="reject",
        reason="Задача не подходит",
    )


class FakeNotifier:
    def __init__(self, error=None):
        self.error = error
        self.orders = []

    async def send_order(self, order):
        if self.error is not None:
            raise self.error
        self.orders.append(order)


class RunnerTest(unittest.IsolatedAsyncioTestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_default_poll_interval_is_ten_seconds(self):
        self.assertEqual(poll_interval_from_env(), 10)

    @patch.dict(
        os.environ,
        {"WORKZILLA_POLL_INTERVAL_SECONDS": "nan"},
        clear=True,
    )
    def test_rejects_invalid_poll_interval(self):
        with self.assertRaisesRegex(ValueError, "must be a positive integer"):
            poll_interval_from_env()

    async def test_writes_order_once_and_restores_index(self):
        orders = [
            {
                "id": 1,
                "subject": "Карточка товара",
                "description": "Сделать инфографику",
                "price": 2500.0,
            }
        ]

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            first_log = DecisionLog(path)
            first_count = await run_once(
                FakeWorkzillaClient(orders),
                first_log,
                analyzer=accept_order,
            )
            second_log = DecisionLog(path)
            second_count = await run_once(
                FakeWorkzillaClient(orders),
                second_log,
                analyzer=accept_order,
            )

            text = path.read_text(encoding="utf-8")
            records = json.loads(text)
            record = records[0]
            mode = path.stat().st_mode & 0o777

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(records), 1)
        self.assertIn("\n  {", text)
        self.assertEqual(record["title"], "Карточка товара")
        self.assertEqual(record["description"], "Сделать инфографику")
        self.assertEqual(record["price"], 2500.0)
        self.assertEqual(record["verdict"], "accept")
        self.assertEqual(mode, 0o600)

    async def test_ignores_changed_order_with_known_id(self):
        order = {
            "id": 1,
            "subject": "Логотип",
            "description": "Первое описание",
        }

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            decision_log = DecisionLog(path)
            await run_once(
                FakeWorkzillaClient([order]),
                decision_log,
                analyzer=accept_order,
            )
            order["description"] = "Новое описание"
            second_count = await run_once(
                FakeWorkzillaClient([order]),
                decision_log,
                analyzer=accept_order,
            )
            records = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(second_count, 0)
        self.assertEqual(len(records), 1)

    async def test_deduplicates_same_order_inside_poll(self):
        order = {
            "id": 1,
            "subject": "Логотип",
            "description": "Создать логотип",
        }

        with TemporaryDirectory() as temp_dir:
            decision_log = DecisionLog(Path(temp_dir) / "decisions.json")
            count = await run_once(
                FakeWorkzillaClient([order, order]),
                decision_log,
                analyzer=accept_order,
            )

        self.assertEqual(count, 1)

    async def test_continues_after_model_error_for_one_order(self):
        async def sometimes_fails(order):
            if order.order_id == "1":
                raise LLMError("temporary error")
            return await accept_order(order)

        orders = [
            {"id": 1, "subject": "Первый", "description": "Описание"},
            {"id": 2, "subject": "Второй", "description": "Описание"},
        ]

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            count = await run_once(
                FakeWorkzillaClient(orders),
                DecisionLog(path),
                analyzer=sometimes_fails,
            )
            records = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["order_id"], "2")

    async def test_notifies_only_about_accepted_order(self):
        orders = [
            {"id": 1, "subject": "Дизайн", "description": "Баннер"},
            {"id": 2, "subject": "Видео", "description": "Монтаж"},
        ]
        notifier = FakeNotifier()

        async def analyzer(order):
            if order.order_id == "1":
                return await accept_order(order)
            return await reject_order(order)

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            count = await run_once(
                FakeWorkzillaClient(orders),
                DecisionLog(path),
                analyzer=analyzer,
                notifier=notifier,
            )
            records = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(count, 2)
        self.assertEqual([order.order_id for order in notifier.orders], ["1"])
        self.assertTrue(records[0]["telegram_notified"])
        self.assertNotIn("telegram_notified", records[1])

    async def test_does_not_load_customer_name_during_order_poll(self):
        order = {
            "id": 1,
            "subject": "Дизайн",
            "description": "Сделать баннер",
            "customerId": 99,
        }
        client = FakeWorkzillaClient([order], {"99": "Анна"})
        notifier = FakeNotifier()

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            decision_log = DecisionLog(path)
            await run_once(
                client,
                decision_log,
                analyzer=accept_order,
                notifier=notifier,
            )
            await run_once(
                client,
                DecisionLog(path),
                analyzer=accept_order,
                notifier=notifier,
            )
            records = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(client.customer_requests, [])
        self.assertEqual(records[0]["customer_id"], "99")
        self.assertIsNone(records[0]["customer_name"])
        self.assertIsNone(notifier.orders[0].customer_name)

    def test_persists_generated_reply(self):
        order = OrderDecision(
            order=normalize_order(
                {
                    "id": 1,
                    "subject": "Дизайн",
                    "description": "Баннер",
                }
            ),
            verdict="accept",
            reason="Подходит",
        )

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            decision_log = DecisionLog(path)
            decision_log.append(order)
            decision_log.save_generated_reply("1", "Здравствуйте! Готов помочь 🎨")
            restored = DecisionLog(path)

        self.assertEqual(
            restored.get_generated_reply("1"),
            "Здравствуйте! Готов помочь 🎨",
        )

    async def test_retries_saved_notification_without_reanalysis(self):
        order = {"id": 1, "subject": "Дизайн", "description": "Баннер"}
        failing_notifier = FakeNotifier(TelegramError("temporary error"))

        async def unexpected_analyzer(order):
            self.fail("A persisted order must not be analyzed again")

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "decisions.json"
            first_count = await run_once(
                FakeWorkzillaClient([order]),
                DecisionLog(path),
                analyzer=accept_order,
                notifier=failing_notifier,
            )
            pending_records = json.loads(path.read_text(encoding="utf-8"))

            working_notifier = FakeNotifier()
            second_count = await run_once(
                FakeWorkzillaClient([order]),
                DecisionLog(path),
                analyzer=unexpected_analyzer,
                notifier=working_notifier,
            )
            delivered_records = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(first_count, 1)
        self.assertFalse(pending_records[0]["telegram_notified"])
        self.assertEqual(second_count, 0)
        self.assertTrue(delivered_records[0]["telegram_notified"])
        self.assertEqual(
            [order.order_id for order in working_notifier.orders],
            ["1"],
        )
