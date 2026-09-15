"""Supplied 3-sigma anomaly baseline ranking implementation."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List
import numpy as np
import pandas as pd

from app.ranking.interface import BaseRanker
from app.data.processor import normalize_gateway_id, filter_active_gateways


class ThreeSigmaRanker(BaseRanker):
    """Production 3-sigma anomaly ranker matching the baseline methodology."""

    METRICS: List[str] = ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]
    BASELINE_DAYS: int = 28
    RECENT_DAYS: int = 7
    SIGMA: float = 3.0

    @property
    def name(self) -> str:
        return "baseline_3sigma"

    def rank_week(
        self,
        monday: dt.date,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        top_n: int = 15,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Rank gateways for the specified Monday based on 3-sigma anomalies."""
        active_master = filter_active_gateways(gateway_master_df)
        active_ids = set(active_master["gateway_id"].dropna().unique())

        end = pd.Timestamp(monday, tz="UTC")
        start_baseline = end - dt.timedelta(days=self.BASELINE_DAYS)
        start_recent = end - dt.timedelta(days=self.RECENT_DAYS)

        window = telemetry_df[(telemetry_df["ts"] >= start_baseline) & (telemetry_df["ts"] < end)].copy()
        # Filter to active gateways only
        if active_ids:
            window = window[window["gateway_id"].isin(active_ids)]

        if window.empty:
            return pd.DataFrame(columns=["week_start", "rank", "gateway_id", "score", "reason"])

        stats = window.groupby("gateway_id")[self.METRICS].agg(["mean", "std"])
        recent = window[window["ts"] >= start_recent].copy()

        flags = pd.Series(0, index=recent.index, dtype=int)
        worst = pd.Series("", index=recent.index, dtype=object)

        for metric in self.METRICS:
            mean = recent["gateway_id"].map(stats[(metric, "mean")])
            std = recent["gateway_id"].map(stats[(metric, "std")]).replace(0, np.nan)
            exceeded = (recent[metric] - mean) > self.SIGMA * std
            exceeded = exceeded.fillna(False)
            flags = flags + exceeded.astype(int)
            worst = worst.where(~exceeded | (worst != ""), metric)

        recent["flagged"] = flags
        recent["worst_metric"] = worst

        grouped = recent.groupby("gateway_id").agg(
            flagged_hours=("flagged", "sum"),
            worst_metric=("worst_metric", lambda s: next((v for v in s if v), "")),
        ).reset_index()

        # Sort descending by flagged_hours
        ranked = grouped.sort_values("flagged_hours", ascending=False).reset_index(drop=True)

        # Build final top_n rows
        rows = []
        for rank_idx, row in enumerate(ranked.head(top_n).itertuples(index=False), start=1):
            metric_desc = row.worst_metric or "no metric over 3 sigma"
            rows.append({
                "week_start": monday.isoformat(),
                "rank": rank_idx,
                "gateway_id": row.gateway_id,
                "score": float(row.flagged_hours),
                "reason": (
                    f"{row.flagged_hours} hour(s) beyond 3 sigma of this gateway's own "
                    f"28-day baseline in the last 7 days; first breach on {metric_desc}"
                )[:300],
            })

        return pd.DataFrame(rows)

    def explain_gateway(
        self,
        monday: dt.date,
        gateway_id: str,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return diagnostic explanation for a single gateway."""
        norm_id = normalize_gateway_id(gateway_id)
        ranked = self.rank_week(monday, telemetry_df, gateway_master_df, top_n=300)
        gw_row = ranked[ranked["gateway_id"] == norm_id]
        if gw_row.empty:
            return {
                "gateway_id": norm_id,
                "week_start": monday.isoformat(),
                "rank": None,
                "score": 0.0,
                "reason": "Gateway had no flagged hours or insufficient data in this window",
            }
        rec = gw_row.iloc[0]
        return {
            "gateway_id": norm_id,
            "week_start": monday.isoformat(),
            "rank": int(rec["rank"]),
            "score": float(rec["score"]),
            "reason": rec["reason"],
        }
