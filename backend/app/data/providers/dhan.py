"""DhanHQ v2 historical data adapter.

Verified against https://dhanhq.co/docs/v2/ on 2026-11-01; see docs/market-data.md. Facts the
documentation leaves open, such as the epoch timezone and index volume, are checked by the data
validator rather than assumed here.
"""

import csv
import io
import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

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
    ProviderSubscriptionError,
    ProviderUnavailableError,
)
from app.data.providers.http import RetryingTransport, index_volume, is_number, json_body
from app.domain.candle import NIFTY50, Candle
from app.domain.enums import Timeframe


API_BASE_URL = "https://api.dhan.co/v2"
SECURITY_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

INDEX_SEGMENT = "IDX_I"
INDEX_INSTRUMENT = "INDEX"
INTRADAY_INTERVALS = {Timeframe.M5: "5"}

# Documented: "only 90 days of data can be polled at once".
INTRADAY_CHUNK_DAYS = 90
# Not documented for daily candles, so this is a cautious choice.
DAILY_CHUNK_DAYS = 365
INTRADAY_HISTORY_YEARS = 5
# Documented: 5 Data API requests per second. Stay just under it.
MIN_REQUEST_INTERVAL_SECONDS = 0.25

AUTH_ERRORS = {"DH-901", "807", "808", "809", "810"}
SUBSCRIPTION_ERRORS = {"DH-902", "806"}
RATE_LIMIT_ERRORS = {"DH-904", "805"}
RETRYABLE_SERVER_ERRORS = {"DH-908", "DH-909", "800"}

# Exact-match keys: the master also lists indices such as "Nifty50 Shariah".
_NIFTY50_MASTER_ROW = {
    "SEM_EXM_EXCH_ID": "NSE",
    "SEM_SEGMENT": "I",
    "SEM_INSTRUMENT_NAME": "INDEX",
    "SEM_TRADING_SYMBOL": "NIFTY",
    "SEM_CUSTOM_SYMBOL": "Nifty 50",
}


class DhanProvider(MarketDataProvider):
    code = "dhan"

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
            "dhan",
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
        response = self._send("GET", SECURITY_MASTER_URL, authenticated=False)
        matches = [
            row
            for row in csv.DictReader(io.StringIO(response.text))
            if all(row.get(key) == value for key, value in _NIFTY50_MASTER_ROW.items())
        ]
        if len(matches) != 1 or not matches[0].get("SEM_SMST_SECURITY_ID"):
            raise InstrumentNotFoundError(
                f"Expected exactly one NIFTY 50 row in the security master, found {len(matches)}"
            )
        return ProviderInstrument(
            symbol=symbol,
            provider=self.code,
            security_id=matches[0]["SEM_SMST_SECURITY_ID"],
            exchange_segment=INDEX_SEGMENT,
            instrument_type=INDEX_INSTRUMENT,
            source=SECURITY_MASTER_URL,
        )

    def get_historical_candles(
        self, instrument: ProviderInstrument, timeframe: Timeframe, start: date, end: date
    ) -> ProviderChunk:
        if timeframe not in INTRADAY_INTERVALS:
            raise ValueError(f"Unsupported intraday timeframe: {timeframe}")
        # The time of day spans the whole date under either possible server timezone. The
        # documented example sends a string interval, although the field table says integer.
        return self._fetch_candles(
            f"{API_BASE_URL}/charts/intraday",
            {
                **_instrument_fields(instrument),
                "interval": INTRADAY_INTERVALS[timeframe],
                "oi": False,
                "fromDate": f"{start.isoformat()} 00:00:00",
                "toDate": f"{end.isoformat()} 23:59:59",
            },
            instrument,
            timeframe,
        )

    def get_daily_candles(
        self, instrument: ProviderInstrument, start: date, end: date
    ) -> ProviderChunk:
        # Documented: toDate is non-inclusive for this endpoint.
        return self._fetch_candles(
            f"{API_BASE_URL}/charts/historical",
            {
                **_instrument_fields(instrument),
                "expiryCode": 0,
                "oi": False,
                "fromDate": start.isoformat(),
                "toDate": (end + timedelta(days=1)).isoformat(),
            },
            instrument,
            Timeframe.D1,
        )

    def get_available_history(
        self, instrument: ProviderInstrument, timeframe: Timeframe
    ) -> AvailableHistory:
        if timeframe == Timeframe.D1:
            return AvailableHistory(
                timeframe, None, "Documented as available back to the scrip's inception."
            )
        today = self._clock().date()
        return AvailableHistory(
            timeframe,
            today.replace(year=today.year - INTRADAY_HISTORY_YEARS, day=min(today.day, 28)),
            "Documented as the last 5 years of intraday candles.",
        )

    def validate_connection(self) -> ConnectionStatus:
        if self._token is None:
            return ConnectionStatus(False, "No access token configured.")
        try:
            body = self._send("GET", f"{API_BASE_URL}/profile").json()
        except ProviderAuthError:
            return ConnectionStatus(False, "Access token is invalid or expired.")
        except ProviderError as exc:
            return ConnectionStatus(False, f"Connection check failed: {type(exc).__name__}")
        except ValueError:
            return ConnectionStatus(False, "Profile response was not valid JSON.")
        active = body.get("dataPlan") == "Active"
        return ConnectionStatus(
            connected=True,
            detail="Connected." if active else "Connected, but the Data API plan is not active.",
            data_subscription_active=active,
            token_valid_until=body.get("tokenValidity"),
        )

    def _fetch_candles(
        self,
        url: str,
        payload: dict[str, Any],
        instrument: ProviderInstrument,
        timeframe: Timeframe,
    ) -> ProviderChunk:
        response = self._send("POST", url, json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderResponseError("Candle response was not valid JSON") from exc
        now = self._clock()
        return ProviderChunk(
            candles=parse_candles(body, instrument.symbol, timeframe, self.code, now),
            raw_payload={"request": payload, "response": body},
            requested_at=now,
        )

    def _send(
        self, method: str, url: str, authenticated: bool = True, json: Any = None
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if authenticated:
            if self._token is None:
                raise ProviderAuthError("No Dhan access token configured")
            headers["access-token"] = self._token.get_secret_value()

        return self._transport.send(method, url, headers, json)


def _instrument_fields(instrument: ProviderInstrument) -> dict[str, str]:
    return {
        "securityId": instrument.security_id,
        "exchangeSegment": instrument.exchange_segment,
        "instrument": instrument.instrument_type,
    }


def _raise_for_error(response: httpx.Response) -> None:
    body = json_body(response)
    code = str(body.get("errorCode", "")) if isinstance(body, dict) else ""
    if response.is_success and not code:
        return

    message = body.get("errorMessage", "") if isinstance(body, dict) else ""
    text = f"Dhan error {code or response.status_code}: {message}".rstrip(": ")
    if code in AUTH_ERRORS or response.status_code in (401, 403):
        raise ProviderAuthError(text)
    if code in SUBSCRIPTION_ERRORS:
        raise ProviderSubscriptionError(text)
    if code in RATE_LIMIT_ERRORS or response.status_code == 429:
        raise ProviderRateLimitError(text)
    if code in RETRYABLE_SERVER_ERRORS or response.status_code >= 500:
        raise ProviderUnavailableError(text)
    raise ProviderError(text)


def parse_candles(
    body: Any, symbol: str, timeframe: Timeframe, provider: str, ingested_at: datetime
) -> list[Candle]:
    """Validate the documented parallel-array response and convert it to candles."""
    if not isinstance(body, dict):
        raise ProviderResponseError("Candle response was not a JSON object")
    columns: dict[str, Sequence[Any]] = {}
    for key in ("open", "high", "low", "close", "timestamp"):
        value = body.get(key)
        if not isinstance(value, list):
            raise ProviderResponseError(f"Candle response has no '{key}' array")
        columns[key] = value
    count = len(columns["timestamp"])
    if any(len(column) != count for column in columns.values()):
        raise ProviderResponseError("Candle response arrays have different lengths")

    volumes = body.get("volume")
    if volumes is not None and (not isinstance(volumes, list) or len(volumes) != count):
        raise ProviderResponseError("Candle response 'volume' does not match the other arrays")

    candles = []
    for i in range(count):
        epoch = columns["timestamp"][i]
        if not is_number(epoch):
            raise ProviderResponseError(f"Candle {i} has an invalid timestamp: {epoch!r}")
        prices = [columns[key][i] for key in ("open", "high", "low", "close")]
        if not all(is_number(price) and math.isfinite(price) for price in prices):
            raise ProviderResponseError(f"Candle {i} has an invalid price")
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=datetime.fromtimestamp(epoch, tz=UTC),
                open=float(prices[0]),
                high=float(prices[1]),
                low=float(prices[2]),
                close=float(prices[3]),
                volume=index_volume(volumes[i]) if volumes is not None else None,
                provider=provider,
                ingested_at=ingested_at,
            )
        )
    return candles
