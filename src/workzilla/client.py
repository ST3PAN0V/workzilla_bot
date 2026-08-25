import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

DEFAULT_BASE_URL = "https://client.work-zilla.com"
AGENT_REGISTRATION_URL = (
    "https://work-zilla.com/api/identity/v1/api-agent/save"
)
OPEN_ORDERS_PATH = "/api/order/v6/list/open?hideInsolvoOrders=false"
EMAIL_LOGIN_METHOD = 0
DEFAULT_SESSION_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "workzilla_session.json"
)


class WorkzillaError(RuntimeError):
    """Base error raised by the Workzilla client."""


class WorkzillaConfigurationError(WorkzillaError):
    """Required Workzilla settings are missing."""


class WorkzillaAuthenticationError(WorkzillaError):
    """Workzilla rejected or requires authentication."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise WorkzillaConfigurationError(
            f"Environment variable {name} is required"
        )
    return value


class WorkzillaClient:
    """Minimal async client for email login and open Workzilla orders."""

    def __init__(
        self,
        email: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        session_path: str | Path | None = DEFAULT_SESSION_PATH,
    ) -> None:
        self.email = email or _required_env("WORKZILLA_EMAIL")
        self.session_path = Path(session_path) if session_path else None
        session = self._load_session()
        self.agent_id = session.get("agent_id") or f"uid-{uuid4()}"
        cookies = self._load_cookies(session)
        self._agent_registered = False
        self._customer_names: dict[str, str | None] = {}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url
            or os.getenv("WORKZILLA_BASE_URL", DEFAULT_BASE_URL),
            headers={"agentId": self.agent_id},
            cookies=cookies,
            timeout=30,
        )
        if client is not None:
            self._client.cookies.update(cookies)

    async def __aenter__(self) -> "WorkzillaClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request_login_code(self) -> dict[str, Any]:
        """Send a one-time login code to the configured email."""
        await self._ensure_agent_registered()
        data = await self._post_auth(
            "/account/send-login-code",
            {
                "destination": self.email,
                "method": EMAIL_LOGIN_METHOD,
                "captcha": "",
                "fp": self.agent_id,
                "tempDataId": "",
                "disableUserCall": "true",
            },
        )
        response_data = data.get("Data")
        return response_data if isinstance(response_data, dict) else {}

    async def login(self, code: str) -> str | None:
        """Authenticate the current session using an emailed one-time code."""
        code = code.strip()
        if not code:
            raise ValueError("Login code must not be empty")

        data = await self._post_auth(
            "/account/login",
            {
                "login": self.email,
                "method": EMAIL_LOGIN_METHOD,
                "loginCode": code,
                "g-recaptcha-response": "",
                "fp": self.agent_id,
                "tempDataId": "",
            },
        )
        self.save_session()
        redirect = data.get("Redirect")
        return redirect if isinstance(redirect, str) else None

    def save_session(self) -> None:
        """Persist session cookies locally for later client runs."""
        if self.session_path is None:
            return

        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            for cookie in self._client.cookies.jar
        ]
        data = {"agent_id": self.agent_id, "cookies": cookies}
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.session_path.chmod(0o600)

    async def get_open_orders(self) -> list[dict[str, Any]]:
        """Return the open order list shown on the freelancer page."""
        await self._ensure_agent_registered()
        try:
            response = await self._client.get(OPEN_ORDERS_PATH)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 401:
                raise WorkzillaAuthenticationError(
                    "Workzilla authentication is required"
                ) from error
            raise WorkzillaError(
                f"Workzilla returned HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise WorkzillaError(f"Could not connect to Workzilla: {error}") from error

        data = self._json(response)
        if data.get("result") != 0:
            raise WorkzillaError(
                f"Workzilla returned result {data.get('result')} for open orders"
            )
        if not isinstance(data.get("data"), dict):
            raise WorkzillaError("Workzilla returned an unexpected response")

        order_groups = data["data"]
        orders: list[dict[str, Any]] = []
        for name in ("other", "interesting", "withoutSubscriptionRenew"):
            group = order_groups.get(name, [])
            if not isinstance(group, list):
                raise WorkzillaError("Workzilla returned an unexpected order list")
            orders.extend(order for order in group if isinstance(order, dict))
        return orders

    async def get_customer_name(self, customer_id: str) -> str | None:
        """Return the customer's public first name, if Workzilla exposes it."""
        if customer_id in self._customer_names:
            return self._customer_names[customer_id]

        await self._ensure_agent_registered()
        try:
            response = await self._client.get(f"/api/user/v1/{customer_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WorkzillaError(
                f"Workzilla returned HTTP {error.response.status_code} "
                "for customer profile"
            ) from error
        except httpx.HTTPError as error:
            raise WorkzillaError(
                f"Could not connect to Workzilla: {error}"
            ) from error

        data = self._json(response)
        profile = data.get("data")
        if data.get("result") != 0 or not isinstance(profile, dict):
            raise WorkzillaError("Workzilla returned an invalid customer profile")
        raw_name = profile.get("name") or profile.get("fullTitle")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        result = name or None
        self._customer_names[customer_id] = result
        return result

    async def _ensure_agent_registered(self) -> None:
        if self._agent_registered:
            return
        try:
            response = await self._client.post(
                AGENT_REGISTRATION_URL,
                json={"agentId": self.agent_id, "type": 2},
                headers={"agentId": self.agent_id},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WorkzillaError(
                "Workzilla rejected client identifier registration"
            ) from error
        except httpx.HTTPError as error:
            raise WorkzillaError(f"Could not connect to Workzilla: {error}") from error

        data = self._json(response)
        if data.get("result") != 0:
            raise WorkzillaError(
                "Workzilla could not register the client identifier"
            )
        self._agent_registered = True

    async def _post_auth(self, path: str, form: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                path,
                data=form,
                headers={"x-requested-with": "XMLHttpRequest"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WorkzillaAuthenticationError(
                f"Workzilla returned HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise WorkzillaError(f"Could not connect to Workzilla: {error}") from error

        data = self._json(response)
        if data.get("Success") is not True:
            reason = data.get("I18nKey") or data.get("Error") or "unknown error"
            raise WorkzillaAuthenticationError(
                f"Workzilla authentication failed: {reason}"
            )
        return data

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as error:
            raise WorkzillaError("Workzilla returned invalid JSON") from error
        if not isinstance(data, dict):
            raise WorkzillaError("Workzilla returned an unexpected response")
        return data

    def _load_session(self) -> dict[str, Any]:
        if self.session_path is None or not self.session_path.exists():
            return {}
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WorkzillaConfigurationError(
                f"Could not read Workzilla session from {self.session_path}"
            ) from error
        if not isinstance(data, dict):
            raise WorkzillaConfigurationError("Invalid Workzilla session file")
        return data

    @staticmethod
    def _load_cookies(session: dict[str, Any]) -> httpx.Cookies:
        cookies = httpx.Cookies()
        stored_cookies = session.get("cookies", [])
        if not isinstance(stored_cookies, list):
            raise WorkzillaConfigurationError("Invalid Workzilla session cookies")
        for cookie in stored_cookies:
            if not isinstance(cookie, dict):
                raise WorkzillaConfigurationError("Invalid Workzilla session cookie")
            try:
                cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                )
            except (KeyError, TypeError) as error:
                raise WorkzillaConfigurationError(
                    "Invalid Workzilla session cookie"
                ) from error
        return cookies
