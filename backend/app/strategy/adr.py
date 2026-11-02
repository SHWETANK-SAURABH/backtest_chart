"""ADR (strategy.pine 271-321).

The daily ADR is ta.sma(high - low, length) over completed sessions, as request.security with
lookahead_off returns on historical intraday bars. Today's session counts only on its final bar.

Deliberate difference: the script reads today's high and low with lookahead_on, so on past bars
its usage and remaining values see the whole day's range. Here they use the range so far.
"""

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from app.strategy.pine import NA

CONTRACTION_RATIO = 0.65
EXPANSION_RATIO = 1.25


@dataclass(frozen=True)
class AdrState:
    value: float
    usage_percent: float
    current_range: float
    remaining: float
    high_75: float
    high_100: float
    high_125: float
    low_75: float
    low_100: float
    low_125: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyAdr:
    """Fed one completed session at a time."""

    def __init__(self, length: int) -> None:
        self._length = length
        self._ranges: deque[float] = deque(maxlen=length)
        self.value = NA
        self._sessions = 0
        self._last_contraction: int | None = None
        self._last_expansion: int | None = None

    def _average(self, ranges: list[float]) -> float:
        return sum(ranges) / self._length if len(ranges) == self._length else NA

    def add_session(self, high: float, low: float) -> None:
        session_range = high - low
        self._ranges.append(session_range)
        self.value = self._average(list(self._ranges))
        self._sessions += 1
        if session_range < self.value * CONTRACTION_RATIO:
            self._last_contraction = self._sessions
        if session_range > self.value * EXPANSION_RATIO:
            self._last_expansion = self._sessions

    def value_including(self, high: float, low: float) -> float:
        """The ADR once a just-finished session is included, without recording it."""
        return self._average([*self._ranges, high - low][-self._length :])

    @property
    def message(self) -> str:
        contraction_more_recent = self._last_contraction is not None and (
            self._last_expansion is None or self._last_expansion < self._last_contraction
        )
        return "125% breakout possible" if contraction_more_recent else "Play Within Range"


def adr_state(value: float, session_open: float, high: float, low: float, message: str) -> AdrState:
    session_range = high - low
    return AdrState(
        value=value,
        usage_percent=(session_range / value) * 100 if value != 0 else NA,
        current_range=session_range,
        remaining=value - session_range,
        high_75=session_open + value * 0.75,
        high_100=session_open + value,
        high_125=session_open + value * 1.25,
        low_75=session_open - value * 0.75,
        low_100=session_open - value,
        low_125=session_open - value * 1.25,
        message=message,
    )
