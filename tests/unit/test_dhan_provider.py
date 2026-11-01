"""Dhan adapter behaviour. All HTTP responses here are mocks, shaped as the official docs say."""

import json
from datetime import UTC, date, datetime

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
    ProviderSubscriptionError,
    ProviderUnavailableError,
)
from app.data.providers.dhan import DhanProvider, parse_candles
from app.domain.enums import Timeframe

NOW = datetime(2026, 6, 15, tzinfo=UTC)
INSTRUMENT = ProviderInstrument("NIFTY50", "dhan", "13", "IDX_I", "INDEX", "mock")
MASTER_HEADER = (
    "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,"
    "SEM_CUSTOM_SYMBOL\n"
)
NIFTY_ROW = "NSE,I,13,INDEX,NIFTY,Nifty 50\n"
SHARIAH_ROW = "NSE,I,833,INDEX,Nifty50 Shariah,Nifty 50 Shariah\n"
# 2026-06-15 09:15 IST.
EPOCH = 1781495100
CANDLES = {
    "open": [100.0],
    "high": [101.0],
    "low": [99.0],
    "close": [100.5],
    "volume": [0],
    "timestamp": [EPOCH],
}


def provider(handler, token: str | None = "test-token") -> tuple[DhanProvider, list[float]]:
    sleeps: list[float] = []
    instance = DhanProvider(
        SecretStr(token) if token else None,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        clock=lambda: NOW,
    )
    return instance, sleeps


def test_resolves_only_the_exact_nifty_50_row() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "access-token" not in request.headers
        return httpx.Response(200, text=MASTER_HEADER + SHARIAH_ROW + NIFTY_ROW)

    instrument = provider(handler)[0].resolve_instrument("NIFTY50")
    assert instrument.security_id == "13"
    assert instrument.exchange_segment == "IDX_I"
    assert instrument.instrument_type == "INDEX"


@pytest.mark.parametrize("rows", ["", SHARIAH_ROW, NIFTY_ROW + NIFTY_ROW])
def test_missing_or_ambiguous_instrument_is_an_error(rows: str) -> None:
    client = provider(lambda _: httpx.Response(200, text=MASTER_HEADER + rows))[0]
    with pytest.raises(InstrumentNotFoundError):
        client.resolve_instrument("NIFTY50")


def test_other_instruments_are_rejected() -> None:
    client = provider(lambda _: httpx.Response(200))[0]
    with pytest.raises(InstrumentNotFoundError):
        client.resolve_instrument("BANKNIFTY")


def test_intraday_request_matches_the_documented_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers["access-token"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CANDLES)

    chunk = provider(handler)[0].get_historical_candles(
        INSTRUMENT, Timeframe.M5, date(2026, 6, 15), date(2026, 6, 16)
    )
    assert seen["url"] == "https://api.dhan.co/v2/charts/intraday"
    assert seen["token"] == "test-token"
    assert seen["body"] == {
        "securityId": "13",
        "exchangeSegment": "IDX_I",
        "instrument": "INDEX",
        "interval": "5",
        "oi": False,
        "fromDate": "2026-06-15 00:00:00",
        "toDate": "2026-06-16 23:59:59",
    }
    assert chunk.raw_payload["response"] == CANDLES
    assert chunk.candles[0].trading_date == date(2026, 6, 15)
    assert chunk.candles[0].timestamp.tzinfo is not None


def test_daily_end_date_is_extended_because_the_api_excludes_it() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        assert str(request.url) == "https://api.dhan.co/v2/charts/historical"
        return httpx.Response(200, json=CANDLES)

    provider(handler)[0].get_daily_candles(INSTRUMENT, date(2026, 6, 1), date(2026, 6, 30))
    assert seen["fromDate"] == "2026-06-01"
    assert seen["toDate"] == "2026-07-01"


def test_zero_index_volume_becomes_unavailable_not_zero() -> None:
    candles = parse_candles(CANDLES, "NIFTY50", Timeframe.M5, "dhan", NOW)
    assert candles[0].volume is None


def test_positive_volume_is_preserved() -> None:
    body = {**CANDLES, "volume": [500]}
    assert parse_candles(body, "NIFTY50", Timeframe.M5, "dhan", NOW)[0].volume == 500


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {**CANDLES, "close": []},
        {**CANDLES, "close": ["bad"]},
        {**CANDLES, "close": [None]},
        {**CANDLES, "timestamp": ["bad"]},
        {**CANDLES, "volume": [1, 2]},
    ],
)
def test_malformed_responses_are_rejected(body: object) -> None:
    with pytest.raises(ProviderResponseError):
        parse_candles(body, "NIFTY50", Timeframe.M5, "dhan", NOW)


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "DH-901", ProviderAuthError),
        (400, "807", ProviderAuthError),
        (403, "DH-902", ProviderAuthError),
        (400, "806", ProviderSubscriptionError),
        (400, "DH-905", ProviderError),
    ],
)
def test_permanent_errors_are_not_retried(status: int, code: str, expected: type) -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"errorCode": code, "errorMessage": "mock"})

    with pytest.raises(expected):
        provider(handler)[0].get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(calls) == 1


def test_rate_limits_are_retried_with_backoff_then_succeed() -> None:
    responses = [
        httpx.Response(429, json={"errorCode": "DH-904", "errorMessage": "mock"}),
        httpx.Response(200, json={"errorCode": "805", "errorMessage": "mock"}),
        httpx.Response(200, json=CANDLES),
    ]
    client, sleeps = provider(lambda _: responses.pop(0))
    chunk = client.get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(chunk.candles) == 1
    assert 1.0 in sleeps
    assert 2.0 in sleeps


def test_exhausted_rate_limit_retries_raise() -> None:
    client = provider(lambda _: httpx.Response(429))[0]
    with pytest.raises(ProviderRateLimitError):
        client.get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))


def test_network_failures_are_retried_then_raise() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("mock", request=request)

    with pytest.raises(ProviderUnavailableError):
        provider(handler)[0].get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert len(calls) == 5


def test_token_is_not_in_error_messages() -> None:
    client = provider(lambda _: httpx.Response(500))[0]
    with pytest.raises(ProviderError) as caught:
        client.get_daily_candles(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 2))
    assert "test-token" not in str(caught.value)


def test_validate_connection_reports_plan_status() -> None:
    body = {"tokenValidity": "16/06/2026 09:00", "dataPlan": "Deactive"}
    status = provider(lambda _: httpx.Response(200, json=body))[0].validate_connection()
    assert status.connected is True
    assert status.data_subscription_active is False
    assert "not active" in status.detail


def test_validate_connection_without_token_makes_no_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert provider(handler, token=None)[0].validate_connection().connected is False


def test_validate_connection_handles_expired_token() -> None:
    client = provider(lambda _: httpx.Response(401, json={"errorCode": "DH-901"}))[0]
    assert client.validate_connection().connected is False


def test_available_history_reflects_documented_limits() -> None:
    client = provider(lambda _: httpx.Response(200))[0]
    assert client.get_available_history(INSTRUMENT, Timeframe.M5).earliest_date == date(2021, 6, 15)
    assert client.get_available_history(INSTRUMENT, Timeframe.D1).earliest_date is None
    assert client.max_chunk_days(Timeframe.M5) == 90
