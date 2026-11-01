"""Checks against the real provider. Excluded by default; run with: pytest -m live_provider"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.data.ingestion.normalize import to_frame
from app.data.ingestion.validation import validate_candles
from app.data.providers.dhan import DhanProvider
from app.domain.enums import Timeframe

pytestmark = pytest.mark.live_provider


def test_security_master_has_exactly_one_nifty_50_index_row() -> None:
    """The master is public, so this needs no credentials."""
    instrument = DhanProvider(None).resolve_instrument("NIFTY50")
    assert instrument.security_id
    assert instrument.exchange_segment == "IDX_I"


@pytest.mark.skipif("DHAN_ACCESS_TOKEN" not in os.environ, reason="needs DHAN_ACCESS_TOKEN")
def test_recent_real_candles_pass_validation() -> None:
    provider = DhanProvider(SecretStr(os.environ["DHAN_ACCESS_TOKEN"]))
    assert provider.validate_connection().connected
    instrument = provider.resolve_instrument("NIFTY50")
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=10)

    intraday = provider.get_historical_candles(instrument, Timeframe.M5, start, end)
    report = validate_candles(to_frame(intraday.candles), Timeframe.M5)
    assert report.row_count > 0
    assert not report.has_critical_issues, report.to_dict()

    daily = provider.get_daily_candles(instrument, start, end)
    report = validate_candles(to_frame(daily.candles), Timeframe.D1)
    assert report.row_count > 0
    assert not report.has_critical_issues, report.to_dict()
