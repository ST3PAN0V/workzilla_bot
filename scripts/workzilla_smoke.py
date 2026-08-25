import asyncio
import getpass

from dotenv import load_dotenv

from src.workzilla.client import WorkzillaAuthenticationError, WorkzillaClient


async def main() -> None:
    load_dotenv()
    async with WorkzillaClient() as client:
        try:
            orders = await client.get_open_orders()
            print("Использована сохранённая сессия Workzilla")
        except WorkzillaAuthenticationError:
            await client.request_login_code()
            code = getpass.getpass("Код из письма Workzilla: ")
            redirect = await client.login(code)
            if redirect:
                print(f"Вход выполнен, переход Workzilla: {redirect}")
            orders = await client.get_open_orders()

    print(f"Получено заданий: {len(orders)}")
    for order in orders[:10]:
        order_id = order.get("id")
        subject = order.get("subject")
        price = order.get("price")
        print(f"- {order_id}: {subject} ({price})")


if __name__ == "__main__":
    asyncio.run(main())
