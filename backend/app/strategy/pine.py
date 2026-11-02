"""Incremental equivalents of the Pine Script built-ins the strategy uses.

Pine's `na` is represented by NaN. NaN comparisons are false, as `na` comparisons are in Pine, so
ported conditions keep their meaning without extra checks.
"""

import math
from collections import deque

NA = math.nan


def is_na(value: float) -> bool:
    return math.isnan(value)


class Sma:
    """ta.sma: NaN until `length` values have been seen."""

    def __init__(self, length: int) -> None:
        self._values: deque[float] = deque(maxlen=length)
        self._length = length

    def update(self, value: float) -> float:
        self._values.append(value)
        if len(self._values) < self._length:
            return NA
        return sum(self._values) / self._length


class Rma:
    """ta.rma: seeded with the SMA of the first `length` values, then alpha = 1/length."""

    def __init__(self, length: int) -> None:
        self._length = length
        self._seed = Sma(length)
        self._value = NA

    def update(self, value: float) -> float:
        if is_na(self._value):
            self._value = self._seed.update(value)
        else:
            alpha = 1 / self._length
            self._value = alpha * value + (1 - alpha) * self._value
        return self._value


class Ema:
    """ta.ema as documented by TradingView: seeded with the first value, alpha = 2/(length+1).

    Display only in this strategy. The seed is unverified until the TradingView parity test runs.
    """

    def __init__(self, length: int) -> None:
        self._alpha = 2 / (length + 1)
        self._value = NA

    def update(self, value: float) -> float:
        if is_na(self._value):
            self._value = value
        else:
            self._value = self._alpha * value + (1 - self._alpha) * self._value
        return self._value
