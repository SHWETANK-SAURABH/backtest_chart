"""The four reversal candle setups (strategy.pine 1394-1504), evaluated on confirmed bars.

Each setup is confirmed by the current bar. Outside, Doji and Wick setups are labelled on the
previous bar; the Extreme setup is labelled on the current bar. The labelled bar is the signal
candle whose high or low becomes the stop loss.
"""

from collections import deque
from dataclasses import dataclass

from app.strategy.pine import Rma, Sma, is_na

DOJI_SMA_PERIOD = 10
DOJI_TOLERANCE = 0.1
EXTREME_BODY_MAX = 0.85
EXTREME_BODY_MIN = 0.5
EXTREME_BARS_BACK = 50
EXTREME_MULTIPLIER = 2
WICK_MULTIPLIER = 3.5
WICK_CLOSE_THRESHOLD = 0.35


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ReversalSignal:
    code: str  # OR, DR, ER, WR
    is_long: bool
    signal_bar: Bar  # the labelled candle


class ReversalDetector:
    def __init__(self) -> None:
        self._bars: deque[Bar] = deque(maxlen=3)
        self._close_sma = Sma(DOJI_SMA_PERIOD)
        self._previous_sma = float("nan")
        self._body_rma = Rma(EXTREME_BARS_BACK)
        self._range_rma = Rma(EXTREME_BARS_BACK)

    def update(self, bar: Bar) -> list[ReversalSignal]:
        """Signals confirmed at the close of `bar`."""
        self._bars.append(bar)
        average = self._close_sma.update(bar.close)
        average_body = self._body_rma.update(abs(bar.close - bar.open))
        average_candle = self._range_rma.update(abs(bar.high - bar.low))
        previous_average = self._previous_sma
        self._previous_sma = average

        if len(self._bars) < 2:
            return []
        prev = self._bars[-2]
        signals = []
        if len(self._bars) == 3:
            signals.extend(_outside(self._bars[-3], prev, bar))
        signals.extend(_doji(prev, bar, previous_average))
        signals.extend(_extreme(prev, bar, average_body, average_candle))
        signals.extend(_wick(prev, bar))
        return signals


def _outside(two_back: Bar, prev: Bar, bar: Bar) -> list[ReversalSignal]:
    signals = []
    if prev.low < two_back.low and prev.close > two_back.high and bar.close > prev.close:
        signals.append(ReversalSignal("OR", True, prev))
    if prev.high > two_back.high and prev.close < two_back.low and bar.close < prev.close:
        signals.append(ReversalSignal("OR", False, prev))
    return signals


def _doji(prev: Bar, bar: Bar, previous_average: float) -> list[ReversalSignal]:
    candle = prev.high - prev.low
    # Pine yields na when dividing by a zero range, which makes the condition false.
    if candle == 0 or is_na(previous_average):
        return []
    is_doji = abs(prev.close - prev.open) / candle < DOJI_TOLERANCE
    signals = []
    if (
        is_doji
        and prev.high < previous_average
        and bar.close > prev.high
        and bar.close > prev.close
    ):
        signals.append(ReversalSignal("DR", True, prev))
    if is_doji and prev.low > previous_average and bar.close < prev.low and bar.close < prev.close:
        signals.append(ReversalSignal("DR", False, prev))
    return signals


def _extreme(
    prev: Bar, bar: Bar, average_body: float, average_candle: float
) -> list[ReversalSignal]:
    candle = prev.high - prev.low
    big = candle > average_candle * EXTREME_MULTIPLIER
    bearish_body = prev.open - prev.close
    bullish_body = prev.close - prev.open
    long_setup = (
        (bearish_body >= EXTREME_BODY_MAX * candle or bearish_body >= EXTREME_BODY_MIN * candle)
        and big
        and bearish_body > average_body
        and bar.close > bar.open
    )
    short_setup = (
        (bullish_body >= EXTREME_BODY_MAX * candle or bullish_body >= EXTREME_BODY_MIN * candle)
        and big
        and bullish_body > average_body
        and bar.open > bar.close
    )
    signals = []
    if long_setup and bar.close > prev.close:
        signals.append(ReversalSignal("ER", True, bar))
    if short_setup and bar.close < prev.close:
        signals.append(ReversalSignal("ER", False, bar))
    return signals


def _wick(prev: Bar, bar: Bar) -> list[ReversalSignal]:
    top_body = max(prev.close, prev.open)
    bottom_body = min(prev.close, prev.open)
    body = top_body - bottom_body
    candle = prev.high - prev.low
    top_wick = prev.high - top_body
    bottom_wick = bottom_body - prev.low
    signals = []
    bull = bottom_wick > WICK_MULTIPLIER * body and prev.close >= prev.low + candle * (
        1 - WICK_CLOSE_THRESHOLD
    )
    bear = (
        top_wick > WICK_MULTIPLIER * body and prev.close <= prev.low + candle * WICK_CLOSE_THRESHOLD
    )
    if bull and bar.close > prev.close:
        signals.append(ReversalSignal("WR", True, prev))
    if bear and bar.close < prev.close:
        signals.append(ReversalSignal("WR", False, prev))
    return signals
