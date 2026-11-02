"""Upstox adapter behaviour. All HTTP responses here are mocks shaped like the documented ones."""

import gzip
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.data.providers.base import (
    InstrumentNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderInstrument,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.data.providers.upstox import UpstoxProvider, parse_candles
from app.domain.enums import Timeframe

NOW = datetime(2026, 6, 15, tzinfo=UTC)
INSTRUMENT = ProviderInstrument(
    "NIFTY50", "upstox", "NSE_INDEX|Nifty 50", "NSE_INDEX", "INDEX", "mock"
)
NIFTY = {
    "segment": "NSE_INDEX",
    "name": "Nifty 50",
    "exchange": "NSE",
    "instrument_type": "INDEX",
    "instrument_key": "NSE_INDEX|Nifty 50",
    "exchange_token": "26000",
    "trading_symbol": "NIFTY",
}
NEXT_50 = {
    **NIFTY,
    "name": "Nifty Next 50",
    "instrument_key": "NSE_INDEX|Nifty Next 50",
    "trading_symbol": "NIFTYNXT50",
}
CANDLES = {
    "status": "success",
    "data": {
        "candles": [
            ["2026-06-15T09:20:00+05:30", 101.0, 102.0, 100.5, 101.5, 0, 0],
            ["2026-06-15T09:15:00+05:30", 100.0, 101.0, 99.0, 100.5, 0, 0],
        ]
    },
}


def provider(handler, token: str | None = "test-token") -> tuple[UpstoxProvider, list[float]]:
    sleeps: list[float] = []
    instance = UpstoxProvider(
        SecretStr(token) if token else None,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        clock=lambda: NOW,
    )
    return instance, sleeps


def instruments(*records: dict) -> httpx.Response:
    return httpx.Response(200, content=gzip.compress(json.dumps(list(records)).encode()))


def test_resolves_only_the_exact_nifty_50_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return instruments(NEXT_50, NIFTY)

    instrument = provider(handler)[0].resolve_instrument("NIFTY50")
    assert instrument.security_id == "NSE_INDEX|Nifty 50"


@pytest.mark.parametrize("records", [[], [NEXT_50], [NIFTY, NIFTY]])
def test_missing_or_ambiguous_instrument_is_an_error(records: list[dict]) -> None:
    with pytest.raises(InstrumentNotFoundError):
        provider(lambda _: instruments(*records))[0].resolve_instrument("NIFTY50")


def test_unreadable_instrument_file_is_an_error() -> None:
    with pytest.raises(ProviderResponseError):
        provider(lambda _: httpx.Response(200, content=b"not gzip"))[0].resolve_instrument(
            "NIFTY50"
        )


def test_intraday_request_matches_the_documented_url() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=CANDLES)

    chunk = provider(handler)[0].get_historical_candles(
        INSTRUMENT, Timeframe.M5, date(2026, 6, 15), date(2026, 7, 10)
    )
    # The key is URL-encoded, to_date comes first, and from_date starts a day early.
    assert (
        seen["url"]
        == "https://api.upstox.com/v3/historical-candle/NSE_INDEX%7CNifty%2050/minutes/5/2026-07-10/2026-06-14"
    )
    assert seen["auth"] == "Bearer test-token"
    assert chunk.raw_payload["response"] == CANDLES
    assert len(chunk.candles) == 2


def test_daily_request_uses_the_day_unit() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    provider(handler)[0].get_daily_candles(INSTRUMENT, date(2025, 1, 1), date(2025, 12, 31))
    assert seen["url"].endswith("/days/1/2025-12-31/2024-12-31")


def test_candles_are_parsed_with_their_offset_and_zero_volume_is_unavailable() -> None:
    candles = parse_candles(CANDLES, "NIFTY50", Timeframe.M5, "upstox", NOW)
    assert candles[1].timestamp == datetime(2026, 6, 15, 3, 45, tzinfo=UTC)  # 09:15 IST
    assert candles[1].trading_date == date(2026, 6, 15)
    assert candles[1].volume is None
    assert candles[0].open == 101.0


def test_daily_candles_land_on_exchange_midnight() -> None:
    body = {
        "status": "success",
        "data": {"candles": [["2026-06-15T00:00:00+05:30", 1.0, 2.0, 0.5, 1.5, 0, 0]]},
    }
    candle = parse_candles(body, "NIFTY50", Timeframe.D1, "upstox", NOW)[0]
    assert candle.timestamp == datetime(2026, 6, 14, 18, 30, tzinfo=UTC)
    assert candle.trading_date == date(2026, 6, 15)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"status": "success"},
        {"data": {"candles": [["2026-06-15T09:15:00+05:30", 1.0, 2.0]]}},
        {"data": {"candles": [["not a time", 1.0, 2.0, 0.5, 1.5]]}},
        {"data": {"candles": [["2026-06-15T09:15:00", 1.0, 2.0, 0.5, 1.5]]}},  # no offset
        {"data": {"candles": [["2026-06-15T09:15:00+05:30", 1.0, "x", 0.5, 1.5]]}},
        {"data": {"candles": [["2026-06-15T09:15:00+05:30", 1.0, None, 0.5, 1.5]]}},
    ],
)
def test_malformed_responses_are_rejected(body: object) -> None:
    with pytest.raises(ProviderResponseError):
        parse_candles(body, "NIFTY50", Timeframe.M5, "upstox", NOW)


def error(status: int, code: str, flat: bool = False) -> httpx.Response:
    entry = {"errorCode": code, "message": "mock"}
    return httpx.Response(status, json=entry if flat else {"status": "error", "errors": [entry]})


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (error(401, "UDAPI100050"), ProviderAuthError),
        (error(400, "UDAPI100050"), ProviderAuthError),
        (error(400, "UDAPI100067", flat=True), ProviderAuthError),
        (error(400, "UDAPI1148"), ProviderError),
        (error(400, "UDAPI100011"), ProviderError),
    ],
)
def test_permanent_errors_are_not_retried(response: httpx.Response, expected: type) -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return response

    with pytest.raises(expected):
        provider(handler)[0].get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(calls) == 1


def test_error_status_in_a_200_response_is_still_an_error() -> None:
    with pytest.raises(ProviderError, match="UDAPI1015"):
        provider(lambda _: error(200, "UDAPI1015"))[0].get_daily_candles(
            INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2)
        )


def test_rate_limits_are_retried_with_backoff_then_succeed() -> None:
    responses = [
        error(429, "UDAPI10005"),
        error(200, "UDAPI10005"),
        httpx.Response(200, json=CANDLES),
    ]
    client, sleeps = provider(lambda _: responses.pop(0))
    chunk = client.get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(chunk.candles) == 2
    assert 1.0 in sleeps and 2.0 in sleeps


def test_exhausted_retries_raise() -> None:
    with pytest.raises(ProviderRateLimitError):
        provider(lambda _: httpx.Response(429))[0].get_daily_candles(
            INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2)
        )
    with pytest.raises(ProviderUnavailableError):
        provider(lambda _: httpx.Response(503))[0].get_daily_candles(
            INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2)
        )


def test_requests_are_spaced_for_the_30_minute_limit() -> None:
    client, sleeps = provider(lambda _: httpx.Response(200, json=CANDLES))
    for _ in range(3):
        client.get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(sleeps) >= 2
    assert all(s <= 1.0 for s in sleeps)


def test_token_is_not_in_error_messages() -> None:
    with pytest.raises(ProviderError) as caught:
        provider(lambda _: httpx.Response(500))[0].get_daily_candles(
            INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2)
        )
    assert "test-token" not in str(caught.value)


def test_validate_connection_uses_a_historical_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=CANDLES)

    status = provider(handler)[0].validate_connection()
    assert status.connected
    assert "historical data access confirmed" in status.detail
    assert "/historical-candle/NSE_INDEX%7CNifty%2050/days/1/2026-06-15/2026-06-05" in seen["url"]
    assert "profile" not in seen["url"]


@pytest.mark.parametrize("code", ["UDAPI100050", "UDAPI1221"])
def test_validate_connection_reports_refused_tokens(code: str) -> None:
    status = provider(lambda _: error(401, code))[0].validate_connection()
    assert status.connected is False
    assert code in status.detail


def test_validate_connection_rejects_an_unexpected_body() -> None:
    body = {"status": "success"}
    status = provider(lambda _: httpx.Response(200, json=body))[0].validate_connection()
    assert status.connected is False


def test_validate_connection_without_token_makes_no_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert provider(handler, token=None)[0].validate_connection().connected is False


def test_available_history_and_chunks_follow_the_documentation() -> None:
    client = provider(lambda _: httpx.Response(200))[0]
    assert client.get_available_history(INSTRUMENT, Timeframe.M5).earliest_date == date(2022, 1, 1)
    assert client.get_available_history(INSTRUMENT, Timeframe.D1).earliest_date == date(2000, 1, 1)
    # Every 5-minute chunk fits within one month, whatever the month.
    assert client.max_chunk_days(Timeframe.M5) <= 28
    assert timedelta(days=client.max_chunk_days(Timeframe.D1)) < timedelta(days=3652)
