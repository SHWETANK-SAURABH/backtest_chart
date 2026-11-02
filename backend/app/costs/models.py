"""Transaction cost models, kept separate so futures and options charges can be added later."""

from abc import ABC, abstractmethod


class CostModel(ABC):
    code: str

    @abstractmethod
    def round_trip_cost_points(self, entry_price: float, exit_price: float) -> float:
        """Cost of one completed trade, in index points."""


class SpotIndexNoCosts(CostModel):
    """NIFTY 50 spot is not tradable, so no brokerage, STT or exchange charges apply to its points.

    Slippage is an execution assumption and is already in the fill prices.
    """

    code = "spot_index_no_costs"

    def round_trip_cost_points(self, entry_price: float, exit_price: float) -> float:
        return 0.0
