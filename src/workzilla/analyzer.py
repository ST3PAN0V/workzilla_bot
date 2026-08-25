import json
from dataclasses import dataclass
from typing import Awaitable, Callable

from shared_llm.client import ask_llm

from src.workzilla.prompts import (
    ORDER_CLASSIFICATION_PROMPT,
    ORDER_DECISION_RESPONSE_FORMAT,
)

LLMCallable = Callable[..., Awaitable[str]]


class OrderAnalysisError(RuntimeError):
    """Base error raised while preparing or analyzing an order."""


class OrderDataError(OrderAnalysisError):
    """Workzilla returned an order without required fields."""


class ModelResponseError(OrderAnalysisError):
    """The model returned a response that cannot be used as a decision."""


@dataclass(frozen=True)
class OrderData:
    order_id: str
    title: str
    description: str
    price: float | None = None
    customer_id: str | None = None
    customer_name: str | None = None


@dataclass(frozen=True)
class OrderDecision:
    order: OrderData
    verdict: str
    reason: str


def normalize_order(order: dict[str, object]) -> OrderData:
    """Read the fields confirmed in the Workzilla open-order response."""
    raw_order_id = order.get("id")
    if raw_order_id is None or not str(raw_order_id).strip():
        raise OrderDataError("Workzilla order has no id")

    title = order.get("subject")
    description = order.get("description")
    raw_price = order.get("price")
    raw_customer_id = order.get("customerId")
    price = (
        float(raw_price)
        if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool)
        else None
    )

    return OrderData(
        order_id=str(raw_order_id),
        title=title.strip() if isinstance(title, str) else "",
        description=(
            description.strip() if isinstance(description, str) else ""
        ),
        price=price,
        customer_id=(
            str(raw_customer_id)
            if isinstance(raw_customer_id, int)
            and not isinstance(raw_customer_id, bool)
            else None
        ),
    )


def build_user_prompt(order: OrderData) -> str:
    payload = {
        "title": order.title,
        "description": order.description,
    }
    return "Заказ:\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )


def parse_model_response(response: str) -> tuple[bool, str]:
    try:
        data = json.loads(response)
    except (TypeError, json.JSONDecodeError) as error:
        raise ModelResponseError("Model returned invalid JSON") from error

    if not isinstance(data, dict):
        raise ModelResponseError("Model response must be a JSON object")

    suitable = data.get("suitable")
    reason = data.get("reason")
    if not isinstance(suitable, bool):
        raise ModelResponseError("Model response has invalid suitable value")
    if not isinstance(reason, str) or not reason.strip():
        raise ModelResponseError("Model response has no reason")

    return suitable, reason.strip()


async def analyze_order(
    order: OrderData,
    llm: LLMCallable = ask_llm,
) -> OrderDecision:
    """Ask YandexGPT Lite whether an order is suitable."""
    response = await llm(
        build_user_prompt(order),
        system_prompt=ORDER_CLASSIFICATION_PROMPT,
        max_tokens=300,
        temperature=0,
        response_format=ORDER_DECISION_RESPONSE_FORMAT,
    )
    suitable, reason = parse_model_response(response)
    return OrderDecision(
        order=order,
        verdict="accept" if suitable else "reject",
        reason=reason,
    )
