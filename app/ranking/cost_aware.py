"""Cost-aware and risk-weighted gateway ranking strategy.

Enhances the 3-sigma anomaly baseline by incorporating business economics:
- €380 wasted visit penalty vs €600/week broken gateway penalty.
- Meter exposure impact (n_meters_installed ranges from 40 to 900 meters).
- Persistent offline duration vs transient reboot spikes.
- Field visit recency cooldown (prevents redundant repeat dispatch within 7 days).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from app.ranking.interface import BaseRanker
from app.data.processor import normalize_gateway_id, filter_active_gateways
from app.features.engineering import assemble_feature_matrix


class CostRiskRanker(BaseRanker):
    """Business risk-adjusted maintenance ranker.
    
    Combines 3-sigma statistical anomalies with customer meter exposure and
    the €380/€600 economic penalty structure.
    """

    WASTED_VISIT_COST: float = 380.0
    WEEKLY_OUTAGE_PENALTY: float = 600.0

    @property
    def name(self) -> str:
        return "cost_risk_ranker"

    def rank_week(
        self,
        monday: dt.date,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        top_n: int = 15,
        meter_read_df: Optional[pd.DataFrame] = None,
        field_visits_df: Optional[pd.DataFrame] = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Rank active gateways for a given Monday based on risk and expected cost averted."""
        # 1. Ensure active-only gateways
        active_master = filter_active_gateways(gateway_master_df)
        if active_master.empty:
            return pd.DataFrame(columns=["week_start", "rank", "gateway_id", "score", "reason"])

        # 2. Build feature matrix using trailing data up to monday
        feats = assemble_feature_matrix(
            target_monday=monday,
            gateway_master_df=active_master,
            telemetry_df=telemetry_df,
            meter_read_df=meter_read_df,
            field_visits_df=field_visits_df,
        )

        if feats.empty:
            return pd.DataFrame(columns=["week_start", "rank", "gateway_id", "score", "reason"])

        # 3. Calculate risk components
        # Mean meters across network for relative scale (~200)
        mean_meters = active_master["n_meters_installed"].mean()
        if pd.isna(mean_meters) or mean_meters <= 0:
            mean_meters = 200.0

        # Relative exposure weight: ratio of gateway's meter count to network mean
        exposure_weight = (feats["n_meters_installed"] / mean_meters).clip(0.2, 4.5)

        # Failure probability proxy P(Broken) in [0, 1]
        # Driven by 3-sigma anomaly hours, sustained offline hours, and meter loss rate
        anomaly_prob = (feats["flagged_hours"] / 40.0).clip(0.0, 1.0)
        outage_prob = (feats["recent_offline_hours"] / 48.0).clip(0.0, 1.0)
        meter_prob = feats["last_loss_rate"].clip(0.0, 1.0)

        # Composite probability of failure
        p_broken = np.maximum(anomaly_prob * 0.7 + outage_prob * 0.3, meter_prob)

        # Cooldown factor: if visited in last 7 days and not totally offline, reduce repeat dispatch urgency
        cooldown_penalty = np.where((feats["days_since_last_visit"] <= 7) & (feats["recent_offline_hours"] < 12), 0.5, 1.0)

        # Expected financial loss averted per week if visited:
        # Expected Savings = P(broken) * Exposure * €600 - Cost of Visit (€380)
        gross_value = p_broken * exposure_weight * self.WEEKLY_OUTAGE_PENALTY * cooldown_penalty
        score = gross_value.round(2)

        feats["calculated_score"] = score
        feats["p_broken"] = p_broken

        # Sort descending by calculated score, break ties with flagged_hours, then n_meters
        ranked = feats.sort_values(
            by=["calculated_score", "flagged_hours", "n_meters_installed"],
            ascending=[False, False, False],
        ).reset_index(drop=True)

        # Build output rows
        rows = []
        for rank_idx, row in enumerate(ranked.head(top_n).itertuples(index=False), start=1):
            meters = int(row.n_meters_installed)
            flagged = int(row.flagged_hours)
            offline_h = round(float(row.recent_offline_hours), 1)
            reason_str = (
                f"Rank {rank_idx}: {meters} meters at risk. {flagged}h 3-sigma anomalies "
                f"({row.worst_metric}) and {offline_h}h offline in trailing 7d. "
                f"Visiting averts est. €{row.calculated_score:.0f}/wk unread meter loss."
            )[:300]

            rows.append({
                "week_start": monday.isoformat(),
                "rank": rank_idx,
                "gateway_id": row.gateway_id,
                "score": float(row.calculated_score),
                "reason": reason_str,
            })

        return pd.DataFrame(rows)

    def explain_gateway(
        self,
        monday: dt.date,
        gateway_id: str,
        telemetry_df: pd.DataFrame,
        gateway_master_df: pd.DataFrame,
        meter_read_df: Optional[pd.DataFrame] = None,
        field_visits_df: Optional[pd.DataFrame] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Provide detailed diagnostic risk breakdown for a single gateway."""
        norm_id = normalize_gateway_id(gateway_id)
        ranked = self.rank_week(
            monday=monday,
            telemetry_df=telemetry_df,
            gateway_master_df=gateway_master_df,
            top_n=332,
            meter_read_df=meter_read_df,
            field_visits_df=field_visits_df,
        )
        match = ranked[ranked["gateway_id"] == norm_id]
        if match.empty:
            return {
                "gateway_id": norm_id,
                "week_start": monday.isoformat(),
                "rank": None,
                "score": 0.0,
                "reason": "Gateway is either decommissioned or had zero risk indicators in this window",
            }
        rec = match.iloc[0]
        return {
            "gateway_id": norm_id,
            "week_start": monday.isoformat(),
            "rank": int(rec["rank"]),
            "score": float(rec["score"]),
            "reason": rec["reason"],
        }
