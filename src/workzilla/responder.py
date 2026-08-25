import json
from typing import Awaitable, Callable

from shared_llm.client import ask_llm

from src.workzilla.analyzer import OrderData
from src.workzilla.prompts import ORDER_REPLY_PROMPT


LLMCallable = Callable[..., Awaitable[str]]
GREETINGS = (
    "здравствуйте",
    "добрый день",
    "доброе утро",
    "добрый вечер",
    "привет",
)
REPLY_LIMIT = 900


class OrderReplyError(RuntimeError):
    """The model did not return a usable Workzilla reply."""


def build_reply_input(order: OrderData) -> str:
    payload = {
        "customer_name": order.customer_name,
        "title": order.title,
        "description": order.description,
        "price": order.price,
    }
    return "Заказ:\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )


async def generate_order_reply(
    order: OrderData,
    llm: LLMCallable = ask_llm,
) -> str:
    response = await llm(
        build_reply_input(order),
        system_prompt=ORDER_REPLY_PROMPT,
        max_tokens=350,
        temperature=0.5,
    )
    if not isinstance(response, str) or not response.strip():
        raise OrderReplyError("Model returned an empty order reply")

    reply = response.strip()
    if not reply.lower().startswith(GREETINGS):
        reply = "Здравствуйте! " + reply
    if len(reply) > REPLY_LIMIT:
        reply = reply[: REPLY_LIMIT - 3].rstrip() + "..."
    return reply
