import asyncio
import getpass
import logging
from dataclasses import replace

from dotenv import load_dotenv

from src.workzilla.client import (
    WorkzillaAuthenticationError,
    WorkzillaClient,
    WorkzillaError,
)
from src.workzilla.responder import generate_order_reply
from src.workzilla.runner import DecisionLog, poll_interval_from_env, run_forever
from src.workzilla.telegram import TelegramNotifier


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # httpx logs the full Telegram Bot API URL, which contains the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def ensure_authenticated(client: WorkzillaClient) -> None:
    try:
        await client.get_open_orders()
        logging.info("Использована сохранённая сессия Workzilla")
    except WorkzillaAuthenticationError:
        await client.request_login_code()
        code = getpass.getpass("Код из письма Workzilla: ")
        await client.login(code)
        logging.info("Вход в Workzilla выполнен")


async def generate_reply_for_order(
    order_id: str,
    decision_log: DecisionLog,
    client: WorkzillaClient,
) -> str:
    saved_reply = decision_log.get_generated_reply(order_id)
    if saved_reply is not None:
        return saved_reply

    order = decision_log.get_order(order_id)
    if order.customer_name is None and order.customer_id is not None:
        try:
            customer_name = await client.get_customer_name(order.customer_id)
        except WorkzillaError as error:
            logging.warning(
                "Не удалось получить имя заказчика для %s: %s",
                order_id,
                error,
            )
        else:
            if customer_name is not None:
                order = replace(order, customer_name=customer_name)
                decision_log.save_customer_name(order_id, customer_name)

    reply = await generate_order_reply(order)
    decision_log.save_generated_reply(order_id, reply)
    return reply


async def main() -> None:
    load_dotenv()
    configure_logging()
    interval = poll_interval_from_env()
    decision_log = DecisionLog()

    async with WorkzillaClient() as client:
        await ensure_authenticated(client)

        async def reply_to_order(order_id: str) -> str:
            return await generate_reply_for_order(
                order_id,
                decision_log,
                client,
            )

        async with TelegramNotifier(reply_handler=reply_to_order) as notifier:
            logging.info(
                "Для первой настройки отправьте /start боту от @vandoshka"
            )
            await notifier.wait_for_recipient()
            logging.info("Бот запущен, интервал опроса: %s секунд", interval)
            await asyncio.gather(
                run_forever(
                    client,
                    decision_log,
                    interval,
                    notifier=notifier,
                ),
                notifier.run_reply_callbacks(),
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
