import asyncio

from dotenv import load_dotenv

from src.workzilla.analyzer import OrderData, analyze_order


async def main() -> None:
    load_dotenv()
    order = OrderData(
        order_id="smoke-test",
        title="Карточки товара для маркетплейса",
        description="Нужно оформить пять изображений с инфографикой.",
    )
    decision = await analyze_order(order)
    print(f"Вердикт: {decision.verdict}")
    print(f"Причина: {decision.reason}")


if __name__ == "__main__":
    asyncio.run(main())
