"""Upstox v3 historical candle adapter.

Verified against https://upstox.com/developer/api-documentation/ on 2026-11-02; see
docs/market-data.md. NIFTY 50 was confirmed in Upstox's live NSE instrument file as
`NSE_INDEX|Nifty 50` and is resolved from that file at run time.

The documentation does not say whether `from_date` is inclusive or how candles are ordered, so
each request starts a day early and results are sorted and filtered downstream. The error body is
not documented for this endpoint either, so errors are read tolerantly.
"""

import gzip
import json
import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from app.data.providers.base import (
    AvailableHistory,
    ConnectionStatus,
    InstrumentNotFoundError,
    MarketDataProvider,
    ProviderAuthError,
    ProviderChunk,
    ProviderError,
    ProviderInstrument,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.data.providers.http import RetryingTransport, index_volume, is_number, json_body
from app.domain.candle import NIFTY50, Candle
from app.domain.enums import Timeframe

API_BASE_URL = "https://api.upstox.com"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

# Documented: 1 to 15 minute candles return at most "1 month" per request; daily "1 decade".
# 28 days fits within any month; the daily window is likewise kept well inside the limit.
INTRADAY_CHUNK_DAYS = 28
DAILY_CHUNK_DAYS = 3000
INTRADAY_HISTORY_START = date(2022, 1, 1)
DAILY_HISTORY_START = date(2000, 1, 1)
# Documented limits are 50 a second, 500 a minute and 2,000 per 30 minutes. One request a second
# stays under all three, including the 30-minute limit during long downloads.
MIN_REQUEST_INTERVAL_SECONDS = 1.0

# UDAPI1221: the endpoint is only allowed from the account's static IP (seen on the profile
# endpoint with an extended token, 2026-11-02).
AUTH_ERRORS = {"UDAPI100050", "UDAPI100016", "UDAPI100067", "UDAPI100073", "UDAPI1221"}
# Confirmed in the live NSE instrument file on 2026-11-02; used only for the connection check.
NIFTY50_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
RATE_LIMIT_ERRORS = {"UDAPI10005"}
RETRYABLE_SERVER_ERRORS = {"UDAPI100500"}

# Exact-match fields: the file also lists indices such as "Nifty Next 50" and "Nifty50 Value 20".
_NIFTY50_RECORD = {
    "segment": "NSE_INDEX",
    "instrument_type": "INDEX",
    "name": "Nifty 50",
    "trading_symbol": "NIFTY",
}


class UpstoxProvider(MarketDataProvider):
    code = "upstox"

    def __init__(
        self,
        access_token: SecretStr | None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._token = access_token
        self._clock = clock
        self._transport = RetryingTransport(
            "upstox",
            client or httpx.Client(timeout=60, follow_redirects=True),
            sleep,
            MIN_REQUEST_INTERVAL_SECONDS,
            _raise_for_error,
        )

    def max_chunk_days(self, timeframe: Timeframe) -> int:
        return DAILY_CHUNK_DAYS if timeframe == Timeframe.D1 else INTRADAY_CHUNK_DAYS

    def resolve_instrument(self, symbol: str) -> ProviderInstrument:
        if symbol != NIFTY50:
            raise InstrumentNotFoundError(f"Only {NIFTY50} is supported, got {symbol}")
        response = self._send(INSTRUMENTS_URL, authenticated=False)
        try:
            records = json.loads(gzip.decompress(response.content))
        except (OSError, ValueError) as exc:
            raise ProviderResponseError("The instrument file could not be read") from exc
        matches = [
            r
            for r in records
            if isinstance(r, dict) and all(r.get(k) == v for k, v in _NIFTY50_RECORD.items())
        ]
        if len(matches) != 1 or not matches[0].get("instrument_key"):
            raise InstrumentNotFoundError(
                f"Expected exactly one NIFTY 50 record in the instrument file, found {len(matches)}"
            )
        return ProviderInstrument(
            symbol=symbol,
            provider=self.code,
            security_id=matches[0]["instrument_key"],
            exchange_segment="NSE_INDEX",
            instrument_type="INDEX",
            source=INSTRUMENTS_URL,
        )

    def get_historical_candles(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        if timeframe != Timeframe.M5:
            raise ValueError(f"Unsupported intraday timeframe: {timeframe}")
        return self._fetch(instrument, "minutes/5", timeframe, start, end)

    def get_daily_candles(
        self, instrument: ProviderInstrument, start: date, end: date
    ) -> ProviderChunk:
        return self._fetch(instrument, "days/1", Timeframe.D1, start, end)

    def get_available_history(
        self, instrument: ProviderInstrument, timeframe: Timeframe
    ) -> AvailableHistory:
        if timeframe == Timeframe.D1:
            return AvailableHistory(timeframe, DAILY_HISTORY_START, "Documented from January 2000.")
        return AvailableHistory(
            timeframe, INTRADAY_HISTORY_START, "Documented from January 2022 for minute candles."
        )

    def validate_connection(self) -> ConnectionStatus:
        """Checks the access the platform needs: a small NIFTY 50 historical candle request.

        The profile endpoint is not used: extended tokens can be refused there (for example when
        a static IP is required) while historical candles still work.
        """
        if self._token is None:
            return ConnectionStatus(False, "No access token configured.")
        today = self._clock().date()
        key = quote(NIFTY50_INSTRUMENT_KEY, safe="")
        url = (
            f"{API_BASE_URL}/v3/historical-candle/{key}/days/1/"
            f"{today.isoformat()}/{(today - timedelta(days=10)).isoformat()}"
        )
        try:
            body = json_body(self._send(url))
        except ProviderAuthError as exc:
            return ConnectionStatus(False, f"Access token was refused: {exc}")
        except ProviderError as exc:
            return ConnectionStatus(False, f"Connection check failed: {exc}")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("candles"), list):
            return ConnectionStatus(False, "Historical data response was not in the expected form.")
        return ConnectionStatus(True, "Connected: historical data access confirmed.")

    def _fetch(
        self,
        instrument: ProviderInstrument,
        unit_interval: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> ProviderChunk:
        # to_date is documented as inclusive; from_date is not described, so start a day early.
        from_date = start - timedelta(days=1)
        key = quote(instrument.security_id, safe="")
        url = (
            f"{API_BASE_URL}/v3/historical-candle/{key}/{unit_interval}/"
            f"{end.isoformat()}/{from_date.isoformat()}"
        )
        body = json_body(self._send(url))
        if body is None:
            raise ProviderResponseError("Candle response was not valid JSON")
        now = self._clock()
        return ProviderChunk(
            candles=parse_candles(body, instrument.symbol, timeframe, self.code, now),
            raw_payload={"request": {"url": url}, "response": body},
            requested_at=now,
        )

    def _send(self, url: str, authenticated: bool = True) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if authenticated:
            if self._token is None:
                raise ProviderAuthError("No Upstox access token configured")
            headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        return self._transport.send("GET", url, headers)


def _error_code_and_message(body: Any) -> tuple[str, str]:
    """Reads the first error from either a list of errors or a flat error object."""
    if not isinstance(body, dict):
        return "", ""
    errors = body.get("errors")
    entry = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else body
    code = entry.get("errorCode") or entry.get("error_code") or ""
    message = entry.get("message") or entry.get("errorMessage") or ""
    return str(code), str(message)


def _raise_for_error(response: httpx.Response) -> None:
    body = json_body(response)
    failed = isinstance(body, dict) and body.get("status") == "error"
    if response.is_success and not failed:
        return
    code, message = _error_code_and_message(body)
    text = f"Upstox error {code or response.status_code}: {message}".rstrip(": ")
    if code in AUTH_ERRORS or response.status_code in (401, 403):
        raise ProviderAuthError(text)
    if code in RATE_LIMIT_ERRORS or response.status_code == 429:
        raise ProviderRateLimitError(text)
    if code in RETRYABLE_SERVER_ERRORS or response.status_code >= 500:
        raise ProviderUnavailableError(text)
    raise ProviderError(text)


def parse_candles(
    body: Any, symbol: str, timeframe: Timeframe, provider: str, ingested_at: datetime
) -> list[Candle]:
    """Validate the documented `data.candles` arrays: [time, open, high, low, close, volume, oi]."""
    data = body.get("data") if isinstance(body, dict) else None
    rows: Sequence[Any] | None = data.get("candles") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderResponseError("Candle response has no data.candles array")

    candles = []
    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) < 5:
            raise ProviderResponseError(f"Candle {i} is not a [time, open, high, low, close] array")
        try:
            timestamp = datetime.fromisoformat(row[0])
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"Candle {i} has an invalid timestamp: {row[0]!r}") from exc
        if timestamp.tzinfo is None:
            raise ProviderResponseError(f"Candle {i} timestamp has no timezone: {row[0]!r}")
        prices = row[1:5]
        if not all(is_number(p) and math.isfinite(p) for p in prices):
            raise ProviderResponseError(f"Candle {i} has an invalid price")
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp.astimezone(UTC),
                open=float(prices[0]),
                high=float(prices[1]),
                low=float(prices[2]),
                close=float(prices[3]),
                volume=index_volume(row[5]) if len(row) > 5 else None,
                provider=provider,
                ingested_at=ingested_at,
            )
        )
    return candles
