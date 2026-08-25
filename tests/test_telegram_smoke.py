import unittest

from scripts.telegram_smoke import load_first_design_order


class TelegramSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_loads_first_order_from_design_category(self):
        class FakeClient:
            async def get_open_orders(self):
                return [
                    {
                        "id": 1,
                        "categoryId": 7,
                        "subject": "Разработка сайта",
                        "description": "Написать код",
                    },
                    {
                        "id": 2,
                        "categoryId": 141,
                        "subject": "Карточка товара",
                        "description": "Сделать инфографику",
                    },
                    {
                        "id": 3,
                        "categoryId": 141,
                        "subject": "Логотип",
                        "description": "Нарисовать логотип",
                    },
                ]

        order = await load_first_design_order(FakeClient())

        self.assertEqual(order.order_id, "2")
        self.assertEqual(order.title, "Карточка товара")

    async def test_fails_when_design_category_is_empty(self):
        class FakeClient:
            async def get_open_orders(self):
                return [{"id": 1, "categoryId": 7}]

        with self.assertRaisesRegex(RuntimeError, "разделе «Дизайн»"):
            await load_first_design_order(FakeClient())
