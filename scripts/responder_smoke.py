import asyncio

from dotenv import load_dotenv

from src.workzilla.analyzer import OrderData
from src.workzilla.responder import generate_order_reply


async def main() -> None:
    load_dotenv()
    order = OrderData(
        order_id="smoke-test",
        title="Design marketplace product cards",
        description=(
            "Create five clean product cards with benefits and visual accents."
        ),
        price=3000.0,
        customer_name="Анна",
    )
    print(await generate_order_reply(order))


if __name__ == "__main__":
    asyncio.run(main())
