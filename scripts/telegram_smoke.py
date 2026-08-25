import asyncio
import getpass
import logging
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from scripts.run_bot import configure_logging
from src.workzilla.analyzer import OrderData, normalize_order
from src.workzilla.client import (
    WorkzillaAuthenticationError,
    WorkzillaClient,
    WorkzillaError,
)
from src.workzilla.responder import generate_order_reply
from src.workzilla.telegram import TelegramNotifier


RECIPIENT_USERNAME = "ArtemS101"
DESIGN_CATEGORY_ID = 141
CHAT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "telegram_smoke_recipient.json"
)


async def load_first_design_order(client: WorkzillaClient) -> OrderData:
    try:
        orders = await client.get_open_orders()
    except WorkzillaAuthenticationError:
        await client.request_login_code()
        code = getpass.getpass("Код из письма Workzilla: ")
        await client.login(code)
        orders = await client.get_open_orders()

    design_order = next(
        (
            order
            for order in orders
            if order.get("categoryId") == DESIGN_CATEGORY_ID
        ),
        None,
    )
    if design_order is None:
        raise RuntimeError(
            "Workzilla не вернула открытых заказов в разделе «Дизайн»"
        )
    return normalize_order(design_order)


async def main() -> None:
    load_dotenv()
    configure_logging()

    async with WorkzillaClient() as client:
        order = await load_first_design_order(client)

        async with TelegramNotifier(
            chat_path=CHAT_PATH,
            recipient_username=RECIPIENT_USERNAME,
        ) as notifier:
            logging.info(
                "Отправьте /start Telegram-боту от @%s",
                RECIPIENT_USERNAME,
            )
            await notifier.wait_for_recipient()

            if order.customer_id is not None:
                try:
                    customer_name = await client.get_customer_name(
                        order.customer_id
                    )
                except WorkzillaError as error:
                    logging.warning(
                        "Не удалось получить имя заказчика: %s",
                        error,
                    )
                else:
                    if customer_name is not None:
                        order = replace(order, customer_name=customer_name)

            reply = await generate_order_reply(order)
            await notifier.send_order(order)
            await notifier.send_message(f"✍️ Ответ:\n{reply}")

    logging.info(
        "Заказ %s и отклик отправлены @%s",
        order.order_id,
        RECIPIENT_USERNAME,
    )


if __name__ == "__main__":
    asyncio.run(main())
