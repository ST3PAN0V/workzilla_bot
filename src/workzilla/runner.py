import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from shared_llm.client import LLMError

from src.workzilla.analyzer import (
    OrderAnalysisError,
    OrderData,
    OrderDecision,
    analyze_order,
    normalize_order,
)
from src.workzilla.client import (
    WorkzillaAuthenticationError,
    WorkzillaClient,
    WorkzillaError,
)
from src.workzilla.telegram import TelegramError, TelegramNotifier


DEFAULT_DECISIONS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "order_decisions.json"
)
DEFAULT_POLL_INTERVAL_SECONDS = 10

logger = logging.getLogger(__name__)

AnalyzerCallable = Callable[[OrderData], Awaitable[OrderDecision]]


class DecisionLogError(RuntimeError):
    """The decision journal cannot be read or written safely."""


class DecisionLog:
    """Formatted JSON journal and persistent processed-order index."""

    def __init__(self, path: str | Path = DEFAULT_DECISIONS_PATH) -> None:
        self.path = Path(path)
        self._records = self._load_records()
        self._processed = {record["order_id"] for record in self._records}

    def contains(self, order_id: str) -> bool:
        return order_id in self._processed

    def append(
        self,
        decision: OrderDecision,
        telegram_notification_required: bool = False,
    ) -> None:
        record = {
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "order_id": decision.order.order_id,
            "title": decision.order.title,
            "description": decision.order.description,
            "price": decision.order.price,
            "customer_id": decision.order.customer_id,
            "customer_name": decision.order.customer_name,
            "verdict": decision.verdict,
            "reason": decision.reason,
        }
        if telegram_notification_required:
            record["telegram_notified"] = False

        self._records.append(record)
        try:
            self._save()
        except DecisionLogError:
            self._records.pop()
            raise

        self._processed.add(decision.order.order_id)

    def pending_notifications(self) -> list[OrderData]:
        return [
            self._order_from_record(record)
            for record in self._records
            if record.get("telegram_notified") is False
        ]

    def get_order(self, order_id: str) -> OrderData:
        for record in reversed(self._records):
            if record["order_id"] == order_id:
                return self._order_from_record(record)
        raise DecisionLogError(f"Order {order_id} is not in the decision log")

    def get_generated_reply(self, order_id: str) -> str | None:
        for record in reversed(self._records):
            if record["order_id"] == order_id:
                reply = record.get("generated_reply")
                return reply if isinstance(reply, str) else None
        raise DecisionLogError(f"Order {order_id} is not in the decision log")

    def save_generated_reply(self, order_id: str, reply: str) -> None:
        reply = reply.strip()
        if not reply:
            raise DecisionLogError("Generated reply must not be empty")
        for record in reversed(self._records):
            if record["order_id"] == order_id:
                previous = record.get("generated_reply")
                record["generated_reply"] = reply
                try:
                    self._save()
                except DecisionLogError:
                    if previous is None:
                        record.pop("generated_reply", None)
                    else:
                        record["generated_reply"] = previous
                    raise
                return
        raise DecisionLogError(f"Order {order_id} is not in the decision log")

    def save_customer_name(self, order_id: str, customer_name: str) -> None:
        customer_name = customer_name.strip()
        if not customer_name:
            return
        for record in reversed(self._records):
            if record["order_id"] == order_id:
                previous = record.get("customer_name")
                record["customer_name"] = customer_name
                try:
                    self._save()
                except DecisionLogError:
                    record["customer_name"] = previous
                    raise
                return
        raise DecisionLogError(f"Order {order_id} is not in the decision log")

    def mark_notified(self, order_id: str) -> None:
        for record in reversed(self._records):
            if (
                record["order_id"] == order_id
                and record.get("telegram_notified") is False
            ):
                record["telegram_notified"] = True
                try:
                    self._save()
                except DecisionLogError:
                    record["telegram_notified"] = False
                    raise
                return
        raise DecisionLogError(
            f"Order {order_id} has no pending Telegram notification"
        )

    def _load_records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []

        try:
            text = self.path.read_text(encoding="utf-8")
            records = json.loads(text) if text.strip() else []
        except (OSError, json.JSONDecodeError) as error:
            raise DecisionLogError(
                f"Could not read decision log from {self.path}"
            ) from error

        if not isinstance(records, list):
            raise DecisionLogError("Decision log must contain a JSON array")
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise DecisionLogError(
                    f"Invalid decision at {self.path}, index {index}"
                )
            required = ("order_id", "title", "description", "verdict", "reason")
            if any(not isinstance(record.get(key), str) for key in required):
                raise DecisionLogError(
                    f"Invalid decision at {self.path}, index {index}"
                )
            notified = record.get("telegram_notified")
            if notified is not None and not isinstance(notified, bool):
                raise DecisionLogError(
                    f"Invalid decision at {self.path}, index {index}"
                )
            price = record.get("price")
            if (
                price is not None
                and (
                    not isinstance(price, (int, float))
                    or isinstance(price, bool)
                )
            ):
                raise DecisionLogError(
                    f"Invalid decision at {self.path}, index {index}"
                )
            for key in ("customer_id", "customer_name", "generated_reply"):
                value = record.get(key)
                if value is not None and not isinstance(value, str):
                    raise DecisionLogError(
                        f"Invalid decision at {self.path}, index {index}"
                    )
        return records

    @staticmethod
    def _order_from_record(record: dict[str, object]) -> OrderData:
        price = record.get("price")
        customer_id = record.get("customer_id")
        customer_name = record.get("customer_name")
        return OrderData(
            order_id=record["order_id"],
            title=record["title"],
            description=record["description"],
            price=float(price) if isinstance(price, (int, float)) else None,
            customer_id=(
                customer_id if isinstance(customer_id, str) else None
            ),
            customer_name=(
                customer_name if isinstance(customer_name, str) else None
            ),
        )

    def _save(self) -> None:
        temporary_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(self._records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.chmod(0o600)
            temporary_path.replace(self.path)
        except OSError as error:
            raise DecisionLogError(
                f"Could not save decisions to {self.path}"
            ) from error


def poll_interval_from_env() -> int:
    configured = os.getenv("WORKZILLA_POLL_INTERVAL_SECONDS")
    if configured is None:
        return DEFAULT_POLL_INTERVAL_SECONDS
    try:
        interval = int(configured)
    except ValueError as error:
        raise ValueError(
            "WORKZILLA_POLL_INTERVAL_SECONDS must be a positive integer"
        ) from error
    if interval <= 0:
        raise ValueError(
            "WORKZILLA_POLL_INTERVAL_SECONDS must be a positive integer"
        )
    return interval


async def run_once(
    client: WorkzillaClient,
    decision_log: DecisionLog,
    analyzer: AnalyzerCallable = analyze_order,
    notifier: TelegramNotifier | None = None,
) -> int:
    """Analyze every previously unseen order id from one Workzilla poll."""
    if notifier is not None:
        await send_pending_notifications(decision_log, notifier)

    raw_orders = await client.get_open_orders()
    seen_in_poll: set[str] = set()
    decisions_written = 0

    for raw_order in raw_orders:
        try:
            order = normalize_order(raw_order)
        except OrderAnalysisError as error:
            logger.error("Could not normalize Workzilla order: %s", error)
            continue

        if order.order_id in seen_in_poll or decision_log.contains(
            order.order_id
        ):
            continue
        seen_in_poll.add(order.order_id)

        try:
            decision = await analyzer(order)
        except (LLMError, OrderAnalysisError) as error:
            logger.error("Could not analyze order %s: %s", order.order_id, error)
            continue

        notification_required = (
            decision.verdict == "accept" and notifier is not None
        )
        decision_log.append(
            decision,
            telegram_notification_required=notification_required,
        )
        decisions_written += 1

        if notification_required:
            try:
                await notifier.send_order(order)
            except TelegramError as error:
                logger.error(
                    "Could not notify about order %s: %s",
                    order.order_id,
                    error,
                )
            else:
                decision_log.mark_notified(order.order_id)
        logger.info(
            "Order %s: %s (%s)",
            order.order_id,
            decision.verdict,
            decision.reason,
        )

    return decisions_written


async def send_pending_notifications(
    decision_log: DecisionLog,
    notifier: TelegramNotifier,
) -> None:
    for order in decision_log.pending_notifications():
        try:
            await notifier.send_order(order)
        except TelegramError as error:
            logger.error(
                "Could not send pending notification for order %s: %s",
                order.order_id,
                error,
            )
            continue
        decision_log.mark_notified(order.order_id)


async def run_forever(
    client: WorkzillaClient,
    decision_log: DecisionLog,
    interval_seconds: int,
    notifier: TelegramNotifier | None = None,
) -> None:
    """Poll Workzilla until the process is interrupted."""
    while True:
        try:
            decisions_written = await run_once(
                client,
                decision_log,
                notifier=notifier,
            )
            logger.info("Poll complete, new decisions: %s", decisions_written)
        except WorkzillaAuthenticationError:
            logger.error("Workzilla session expired; restart the bot to log in")
            raise
        except WorkzillaError as error:
            logger.error("Workzilla poll failed: %s", error)

        await asyncio.sleep(interval_seconds)
