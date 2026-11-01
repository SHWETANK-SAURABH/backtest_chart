"""The provider-independent candle model."""

from datetime import date
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.domain.enums import Timeframe

EXCHANGE_TIMEZONE = "Asia/Kolkata"
EXCHANGE_TZ = ZoneInfo(EXCHANGE_TIMEZONE)
NIFTY50 = "NIFTY50"


class Candle(BaseModel):
    """One candle, timestamped at bar open.

    OHLC relationships are deliberately not enforced here: bad provider data has to reach the
    validator so it can be reported rather than failing or disappearing during parsing.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    timestamp: AwareDatetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    provider: str
    ingested_at: AwareDatetime

    @property
    def trading_date(self) -> date:
        return self.timestamp.astimezone(EXCHANGE_TZ).date()
