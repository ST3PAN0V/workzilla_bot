import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from src.workzilla.client import (
    WorkzillaAuthenticationError,
    WorkzillaClient,
)


class WorkzillaClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_requests_code_logs_in_and_loads_orders(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/identity/v1/api-agent/save":
                return httpx.Response(200, json={"result": 0})
            if request.url.path == "/account/send-login-code":
                return httpx.Response(
                    200,
                    json={"Success": True, "Data": {"Method": 0}},
                )
            if request.url.path == "/account/login":
                return httpx.Response(
                    200,
                    json={"Success": True, "Redirect": "/freelancer"},
                )
            return httpx.Response(
                200,
                json={
                    "result": 0,
                    "data": {
                        "other": [{"id": 1}],
                        "interesting": [{"id": 2}],
                        "withoutSubscriptionRenew": [{"id": 3}],
                    },
                },
            )

        http_client = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        )
        client = WorkzillaClient(
            email="user@example.test",
            client=http_client,
            session_path=None,
        )

        code_info = await client.request_login_code()
        redirect = await client.login("1234")
        orders = await client.get_open_orders()
        await http_client.aclose()

        self.assertEqual(code_info, {"Method": 0})
        self.assertEqual(redirect, "/freelancer")
        self.assertEqual(orders, [{"id": 1}, {"id": 2}, {"id": 3}])
        code_request = next(
            request
            for request in requests
            if request.url.path == "/account/send-login-code"
        )
        login_request = next(
            request for request in requests if request.url.path == "/account/login"
        )
        self.assertIn(b"destination=user%40example.test", code_request.content)
        self.assertIn(b"disableUserCall=true", code_request.content)
        self.assertIn(b"loginCode=1234", login_request.content)

    async def test_requires_authentication_for_orders(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/identity/v1/api-agent/save":
                return httpx.Response(200, json={"result": 0})
            return httpx.Response(401, json={"result": 10})

        http_client = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        )
        client = WorkzillaClient(
            email="user@example.test",
            client=http_client,
            session_path=None,
        )

        with self.assertRaises(WorkzillaAuthenticationError):
            await client.get_open_orders()

        await http_client.aclose()

    async def test_loads_and_caches_customer_name(self):
        profile_requests = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal profile_requests
            if request.url.path == "/api/identity/v1/api-agent/save":
                return httpx.Response(200, json={"result": 0})
            if request.url.path == "/api/user/v1/99":
                profile_requests += 1
                return httpx.Response(
                    200,
                    json={
                        "result": 0,
                        "data": {"id": 99, "name": " Анна "},
                    },
                )
            return httpx.Response(404)

        http_client = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        )
        client = WorkzillaClient(
            email="user@example.test",
            client=http_client,
            session_path=None,
        )

        first = await client.get_customer_name("99")
        second = await client.get_customer_name("99")
        await http_client.aclose()

        self.assertEqual(first, "Анна")
        self.assertEqual(second, "Анна")
        self.assertEqual(profile_requests, 1)

    async def test_rejects_wrong_login_code(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "Success": False,
                    "I18nKey": "LoginByCode.WrongCodeAttmptsExists",
                },
            )

        http_client = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        )
        client = WorkzillaClient(
            email="user@example.test",
            client=http_client,
            session_path=None,
        )

        with self.assertRaises(WorkzillaAuthenticationError):
            await client.login("wrong-code")

        await http_client.aclose()

    async def test_saves_and_restores_session(self):
        async def login_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "set-cookie": ".AspNetCore.Session=session-value; Path=/; HttpOnly"
                },
                json={"Success": True},
            )

        received_cookie = None

        async def orders_handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_cookie
            received_cookie = request.headers.get("cookie")
            if request.url.path == "/api/identity/v1/api-agent/save":
                return httpx.Response(200, json={"result": 0})
            return httpx.Response(
                200,
                json={
                    "result": 0,
                    "data": {
                        "other": [],
                        "interesting": [],
                        "withoutSubscriptionRenew": [],
                    },
                },
            )

        with TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "workzilla_session.json"
            login_http_client = httpx.AsyncClient(
                base_url="https://example.test",
                transport=httpx.MockTransport(login_handler),
            )
            login_client = WorkzillaClient(
                email="user@example.test",
                client=login_http_client,
                session_path=session_path,
            )
            await login_client.login("1234")
            agent_id = login_client.agent_id
            await login_http_client.aclose()

            self.assertTrue(session_path.exists())
            self.assertEqual(session_path.stat().st_mode & 0o777, 0o600)

            orders_http_client = httpx.AsyncClient(
                base_url="https://example.test",
                transport=httpx.MockTransport(orders_handler),
            )
            orders_client = WorkzillaClient(
                email="user@example.test",
                client=orders_http_client,
                session_path=session_path,
            )
            orders = await orders_client.get_open_orders()
            await orders_http_client.aclose()

            self.assertEqual(orders, [])
            self.assertEqual(orders_client.agent_id, agent_id)
            self.assertEqual(
                received_cookie,
                ".AspNetCore.Session=session-value",
            )
