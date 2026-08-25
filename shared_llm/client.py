import os
from typing import Any

import httpx

DEFAULT_ENDPOINT = "https://llm.api.cloud.yandex.net/v1/chat/completions"
DEFAULT_MODEL = "yandexgpt-5-lite"


class LLMError(RuntimeError):
    """Base error raised by the LLM client."""


class LLMConfigurationError(LLMError):
    """Required Yandex Cloud settings are missing."""


class LLMResponseTruncatedError(LLMError):
    """The model stopped because it reached the output token limit."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise LLMConfigurationError(f"Environment variable {name} is required")
    return value


def _model_uri() -> str:
    configured_uri = os.getenv("YC_MODEL_URI")
    if configured_uri:
        return configured_uri

    folder_id = _required_env("YC_FOLDER_ID")
    model = os.getenv("YC_MODEL", DEFAULT_MODEL)
    return f"gpt://{folder_id}/{model}/latest"


def _extract_text(data: Any) -> str:
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
    except (IndexError, KeyError, TypeError) as error:
        raise LLMError("Yandex Cloud returned an unexpected response") from error

    if choice.get("finish_reason") == "content_filter":
        raise LLMError("Yandex Cloud content filter rejected the request")
    if choice.get("finish_reason") == "length":
        raise LLMResponseTruncatedError(
            "Yandex Cloud response reached the token limit"
        )
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Yandex Cloud returned an empty response")
    return text


async def ask_llm(
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 1000,
    temperature: float = 0.1,
    reasoning_effort: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Send a prompt to Yandex AI Studio and return its text response."""
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    if reasoning_effort not in {
        None,
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }:
        raise ValueError("unsupported reasoning_effort")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": _model_uri(),
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Authorization": f"Api-Key {_required_env('YC_API_KEY')}"}
    endpoint = os.getenv("YC_LLM_ENDPOINT", DEFAULT_ENDPOINT)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        details = error.response.text[:500]
        raise LLMError(
            f"Yandex Cloud returned HTTP {error.response.status_code}: {details}"
        ) from error
    except httpx.HTTPError as error:
        raise LLMError(f"Could not connect to Yandex Cloud: {error}") from error

    try:
        data = response.json()
    except ValueError as error:
        raise LLMError("Yandex Cloud returned invalid JSON") from error
    return _extract_text(data)
