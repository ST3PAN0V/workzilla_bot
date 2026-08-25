import unittest

from src.workzilla.analyzer import (
    ModelResponseError,
    OrderData,
    analyze_order,
    normalize_order,
    parse_model_response,
)


class OrderAnalyzerTest(unittest.IsolatedAsyncioTestCase):
    async def test_does_not_reject_design_for_broad_words(self):
        received = None

        async def fake_llm(prompt, **kwargs):
            nonlocal received
            received = (prompt, kwargs)
            return '{"suitable": true, "reason": "Нужен дизайн логотипа"}'

        order = OrderData(
            order_id="2",
            title="Разработка логотипа",
            description="Создать логотип и подобрать цвета",
        )

        decision = await analyze_order(order, llm=fake_llm)

        self.assertEqual(decision.verdict, "accept")
        self.assertIsNotNone(received)
        prompt, kwargs = received
        self.assertIn("Разработка логотипа", prompt)
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(
            kwargs["response_format"]["json_schema"]["name"],
            "order_decision",
        )

    async def test_design_without_programming_goes_to_model(self):
        async def fake_llm(*args, **kwargs):
            return '{"suitable": true, "reason": "Требуется только дизайн"}'

        order = OrderData(
            order_id="4",
            title="Макет сайта в Figma",
            description="Только дизайн, без программирования",
        )

        decision = await analyze_order(order, llm=fake_llm)

        self.assertEqual(decision.verdict, "accept")

    async def test_user_examples_can_be_accepted_by_model(self):
        async def fake_llm(*args, **kwargs):
            return '{"suitable": true, "reason": "Задача подходит"}'

        examples = (
            (
                "Обработка фото через AI",
                "Переработать фото через нейросеть для улучшения визуала",
            ),
            (
                "Визуализация участка с пристройками",
                "Создать картинки, как может выглядеть участок с беседкой",
            ),
            (
                "ИИ фотосессия в стиле",
                "Сделать фотосессию через ИИ по примеру",
            ),
            (
                "Оценка логотипа компании",
                "Оценить логотип строительной компании",
            ),
            (
                "Оформление канала YouTube",
                "Сделать с нуля обложку и баннер",
            ),
            (
                "Сделать фото чека на фоне машины",
                "Доработать исходное фото через нейросеть или Photoshop",
            ),
            (
                "Описание карточки товара",
                "Написать продающее описание товара для маркетплейса",
            ),
        )

        for index, (title, description) in enumerate(examples, start=1):
            with self.subTest(title=title):
                decision = await analyze_order(
                    OrderData(str(index), title, description),
                    llm=fake_llm,
                )
                self.assertEqual(decision.verdict, "accept")

    async def test_any_static_visual_design_goes_to_model(self):
        async def fake_llm(*args, **kwargs):
            return '{"suitable": true, "reason": "Нужен статичный визуал"}'

        examples = (
            ("Оформление группы VK", "Обложка, аватар и шаблоны постов"),
            ("Оформление Telegram", "Сделать баннеры и набор обложек"),
            ("Оформление Twitch", "Нужны статичные баннер и аватар"),
            (
                "Оформление канала про 3D-моделирование",
                "Сделать статичную обложку для канала про Blender",
            ),
            (
                "Баннер для курса программирования",
                "Нужен рекламный статичный креатив",
            ),
            (
                "Оформление сервиса переводов",
                "Разработать визуальный стиль и обложки",
            ),
        )

        for index, (title, description) in enumerate(examples, start=1):
            with self.subTest(title=title):
                decision = await analyze_order(
                    OrderData(str(index), title, description),
                    llm=fake_llm,
                )
                self.assertEqual(decision.verdict, "accept")

    async def test_model_rejects_excluded_tasks(self):
        async def rejecting_llm(*args, **kwargs):
            return '{"suitable": false, "reason": "Запрещённая задача"}'

        examples = (
            ("Смонтировать ролик", "Создать видео из готовых материалов"),
            ("Создать 3D-модель дома", "Нужен исходник для Blender"),
            ("Написать код", "Разработать приложение"),
            ("Перевести текст", "Перевод на английский язык"),
        )

        for index, (title, description) in enumerate(examples, start=1):
            with self.subTest(title=title):
                decision = await analyze_order(
                    OrderData(str(index), title, description),
                    llm=rejecting_llm,
                )
                self.assertEqual(decision.verdict, "reject")

    def test_normalizes_real_workzilla_fields(self):
        order = normalize_order(
            {
                "id": 42,
                "subject": "Карточка товара",
                "description": "Добавить инфографику",
                "price": 1500.0,
                "customerId": 99,
            }
        )

        self.assertEqual(order.order_id, "42")
        self.assertEqual(order.title, "Карточка товара")
        self.assertEqual(order.description, "Добавить инфографику")
        self.assertEqual(order.price, 1500.0)
        self.assertEqual(order.customer_id, "99")

    def test_rejects_invalid_model_response(self):
        with self.assertRaises(ModelResponseError):
            parse_model_response("not-json")

        with self.assertRaises(ModelResponseError):
            parse_model_response('{"suitable": "yes", "reason": "ok"}')
