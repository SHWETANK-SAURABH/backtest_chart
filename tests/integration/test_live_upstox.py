"""Checks against the real Upstox API. Excluded by default; run with: pytest -m live_provider"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.data.ingestion.normalize import to_frame
from app.data.ingestion.validation import validate_candles
from app.data.providers.upstox import UpstoxProvider
from app.domain.enums import Timeframe

pytestmark = pytest.mark.live_provider


def test_instrument_file_has_exactly_one_nifty_50_index() -> None:
    """The instrument file is public, so this needs no credentials."""
    instrument = UpstoxProvider(None).resolve_instrument("NIFTY50")
    assert instrument.security_id == "NSE_INDEX|Nifty 50"


@pytest.mark.skipif("UPSTOX_ACCESS_TOKEN" not in os.environ, reason="needs UPSTOX_ACCESS_TOKEN")
def test_recent_real_candles_pass_validation() -> None:
    provider = UpstoxProvider(SecretStr(os.environ["UPSTOX_ACCESS_TOKEN"]))
    connection = provider.validate_connection()
    assert connection.connected, connection.detail
    instrument = provider.resolve_instrument("NIFTY50")
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=10)

    for timeframe, chunk in (
        (Timeframe.M5, provider.get_historical_candles(instrument, Timeframe.M5, start, end)),
        (Timeframe.D1, provider.get_daily_candles(instrument, start, end)),
    ):
        frame = to_frame(chunk.candles)
        report = validate_candles(frame.unique(subset=["timestamp"]), timeframe)
        assert report.row_count > 0
        assert not report.has_critical_issues, report.to_dict()
        print(f"\n{timeframe}: {report.row_count} rows, {report.rows_with_volume} with volume")
