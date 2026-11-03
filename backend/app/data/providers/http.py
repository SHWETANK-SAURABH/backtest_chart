"""HTTP plumbing shared by provider adapters: throttling, retries with backoff, parsing helpers."""

import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog

from app.data.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)

log = structlog.get_logger()

MAX_ATTEMPTS = 5


class RetryingTransport:
    """Sends requests no faster than `min_interval`, retrying rate limits and outages.

    `raise_for_error` turns a provider's error response into the matching ProviderError; rate
    limit and unavailable errors are retried with exponential backoff, all others raise at once.
    """

    def __init__(
        self,
        name: str,
        client: httpx.Client,
        sleep: Callable[[float], None],
        min_interval: float,
        raise_for_error: Callable[[httpx.Response], None],
    ) -> None:
        self._name = name
        self._client = client
        self._sleep = sleep
        self._min_interval = min_interval
        self._raise_for_error = raise_for_error
        self._last_request = 0.0

    def send(
        self, method: str, url: str, headers: dict[str, str], json: Any = None
    ) -> httpx.Response:
        failure: ProviderError = ProviderUnavailableError("No attempts were made")
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                self._sleep(2.0 ** (attempt - 1))
            self._throttle()
            try:
                response = self._client.request(method, url, headers=headers, json=json)
            except httpx.TransportError as exc:
                log.warning(
                    f"{self._name}.transport_error", attempt=attempt, error=type(exc).__name__
                )
                failure = ProviderUnavailableError(f"Network failure: {type(exc).__name__}")
                continue
            try:
                self._raise_for_error(response)
            except (ProviderRateLimitError, ProviderUnavailableError) as exc:
                log.warning(f"{self._name}.retryable_error", attempt=attempt, error=str(exc))
                failure = exc
                continue
            return response
        raise failure

    def _throttle(self) -> None:
        wait = self._last_request + self._min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()


def json_body(response: httpx.Response) -> Any:
    """The parsed JSON body, or None when the response is not JSON."""
    if "json" not in response.headers.get("content-type", ""):
        return None
    try:
        return response.json()
    except ValueError:
        return None


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def index_volume(value: Any) -> int | None:
    """An index has no traded volume of its own, so zero means unavailable, not "no trading"."""
    if not is_number(value) or value <= 0:
        return None
    return int(value)
