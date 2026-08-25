import unittest

from src.workzilla.analyzer import OrderData
from src.workzilla.prompts import ORDER_REPLY_PROMPT
from src.workzilla.responder import generate_order_reply


class OrderResponderTest(unittest.IsolatedAsyncioTestCase):
    async def test_passes_customer_and_order_to_reply_prompt(self):
        received = None

        async def fake_llm(prompt, **kwargs):
            nonlocal received
            received = prompt, kwargs
            return "Добрый день, Анна! Готова помочь с макетом, есть опыт 🎨"

        reply = await generate_order_reply(
            OrderData(
                order_id="7",
                title="Макет афиши",
                description="Нужна яркая афиша для мероприятия",
                price=2500.0,
                customer_name="Анна",
            ),
            llm=fake_llm,
        )

        self.assertEqual(
            reply,
            "Добрый день, Анна! Готова помочь с макетом, есть опыт 🎨",
        )
        self.assertIsNotNone(received)
        prompt, kwargs = received
        self.assertIn('"customer_name": "Анна"', prompt)
        self.assertIn('"price": 2500.0', prompt)
        self.assertEqual(kwargs["system_prompt"], ORDER_REPLY_PROMPT)
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["max_tokens"], 350)
        prompt_lower = ORDER_REPLY_PROMPT.lower()
        self.assertIn("от лица девушки", prompt_lower)
        self.assertIn("не благодари за заказ", prompt_lower)
        self.assertIn("написанием кириллицей", prompt_lower)
        self.assertIn("нельзя уверенно распознать как личное имя", prompt_lower)
        self.assertIn("покажи опыт через подход", prompt_lower)
        self.assertIn("заверши одним уместным вопросом", prompt_lower)

    async def test_adds_mandatory_greeting_if_model_omits_it(self):
        async def fake_llm(*args, **kwargs):
            return "Готов качественно оформить карточки товара 🎨"

        reply = await generate_order_reply(
            OrderData("7", "Карточки", "Сделать инфографику"),
            llm=fake_llm,
        )

        self.assertTrue(reply.startswith("Здравствуйте! "))

    async def test_limits_reply_length(self):
        async def fake_llm(*args, **kwargs):
            return "Здравствуйте! " + "опыт " * 200

        reply = await generate_order_reply(
            OrderData("7", "Карточки", "Сделать инфографику"),
            llm=fake_llm,
        )

        self.assertLessEqual(len(reply), 900)
        self.assertTrue(reply.endswith("..."))
