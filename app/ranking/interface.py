"""Abstract interface for pluggable gateway ranking algorithms."""

from __future__ import annotations

import abc
import datetime as dt
from typing import Any, Dict, List
import pandas as pd


class BaseRanker(abc.ABC):
    """Abstract base class defining the contract for gateway ranking algorithms.
    
    Any new ranking strategy (e.g. baseline 3-sigma, heuristic, ML model, or cost-based)
    must inherit from this interface, allowing seamless swapping in the API without modifying
    controller or route logic.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable identifier for the ranker."""
        pass

    @abc.abstractmethod
    def rank_week(
        self,
        monday: dt.date,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        top_n: int = 15,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Rank gateways requiring maintenance for a given Monday.
        
        Returns a DataFrame containing at least:
        - week_start (str, YYYY-MM-DD)
        - rank (int, 1..top_n)
        - gateway_id (str, normalized 12-char hex)
        - score (float)
        - reason (str, <= 300 characters)
        """
        pass

    @abc.abstractmethod
    def explain_gateway(
        self,
        monday: dt.date,
        gateway_id: str,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Provide detailed diagnostic breakdown for a specific gateway."""
        pass
