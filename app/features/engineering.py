"""Feature engineering module for gateway health, anomalies, and business risk.

Extracts features from telemetry, meter read success, field visits, and gateway metadata
strictly using trailing historical data before any target evaluation date (no future leakage).
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


def compute_telemetry_features(
    telemetry_df: pd.DataFrame,
    target_monday: dt.date,
    baseline_days: int = 28,
    recent_days: int = 7,
    sigma: float = 3.0,
) -> pd.DataFrame:
    """Extract rolling baseline and recent anomaly features from telemetry.
    
    Parameters:
    -----------
    telemetry_df: DataFrame with at least ['gateway_id', 'ts', 'offline_duration_sec', 'disconnection_cnt', 'reboot_cnt']
    target_monday: Evaluation Monday date. All data used is strictly < target_monday (no leakage).
    baseline_days: Duration of historical baseline window (default 28 days).
    recent_days: Duration of recent evaluation window (default 7 days).
    sigma: Threshold multiplier for baseline standard deviations.
    """
    end_ts = pd.Timestamp(target_monday, tz="UTC")
    start_baseline = end_ts - dt.timedelta(days=baseline_days)
    start_recent = end_ts - dt.timedelta(days=recent_days)

    window = telemetry_df[(telemetry_df["ts"] >= start_baseline) & (telemetry_df["ts"] < end_ts)].copy()
    if window.empty:
        return pd.DataFrame(columns=[
            "gateway_id", "flagged_hours", "worst_metric",
            "recent_offline_hours", "recent_disconnections", "recent_reboots",
            "recent_offline_sec", "mean_offline_sec", "std_offline_sec"
        ])

    tracked_metrics = ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]
    stats = window.groupby("gateway_id")[tracked_metrics].agg(["mean", "std"])

    recent = window[window["ts"] >= start_recent].copy()
    if recent.empty:
        return pd.DataFrame(columns=["gateway_id", "flagged_hours", "worst_metric"])

    flags = pd.Series(0, index=recent.index, dtype=int)
    worst = pd.Series("", index=recent.index, dtype=object)

    for metric in tracked_metrics:
        mean_val = recent["gateway_id"].map(stats[(metric, "mean")])
        std_val = recent["gateway_id"].map(stats[(metric, "std")]).replace(0, np.nan)
        exceeded = (recent[metric] - mean_val) > (sigma * std_val)
        exceeded = exceeded.fillna(False)
        flags = flags + exceeded.astype(int)
        worst = worst.where(~exceeded | (worst != ""), metric)

    recent["flagged"] = flags
    recent["worst_metric"] = worst

    # Aggregations per gateway
    grouped = recent.groupby("gateway_id").agg(
        flagged_hours=("flagged", "sum"),
        worst_metric=("worst_metric", lambda s: next((v for v in s if v), "none")),
        recent_offline_sec=("offline_duration_sec", "sum"),
        recent_disconnections=("disconnection_cnt", "sum"),
        recent_reboots=("reboot_cnt", "sum"),
    ).reset_index()

    # Derived hours offline
    grouped["recent_offline_hours"] = grouped["recent_offline_sec"] / 3600.0

    # Optional extra columns if present in telemetry (e.g. signal quality)
    if "rssi_bad" in recent.columns:
        rssi_agg = recent.groupby("gateway_id")["rssi_bad"].sum().reset_index()
        grouped = grouped.merge(rssi_agg, on="gateway_id", how="left")

    if "network_2g" in recent.columns:
        net2g_agg = recent.groupby("gateway_id")["network_2g"].sum().reset_index()
        grouped = grouped.merge(net2g_agg, on="gateway_id", how="left")

    return grouped


def compute_meter_read_features(
    meter_read_df: pd.DataFrame,
    target_monday: dt.date,
    lookback_weeks: int = 4,
) -> pd.DataFrame:
    """Extract meter reading failure rate and unread meter statistics before target_monday."""
    if meter_read_df.empty or "week_start_date" not in meter_read_df.columns:
        return pd.DataFrame(columns=["gateway_id", "avg_loss_rate", "avg_unread_meters", "last_loss_rate"])

    # Strict historical filter (strictly before target_monday)
    hist = meter_read_df[meter_read_df["week_start_date"] < target_monday].copy()
    if hist.empty:
        return pd.DataFrame(columns=["gateway_id", "avg_loss_rate", "avg_unread_meters", "last_loss_rate"])

    cutoff_date = target_monday - dt.timedelta(weeks=lookback_weeks)
    recent_hist = hist[hist["week_start_date"] >= cutoff_date].copy()
    if recent_hist.empty:
        recent_hist = hist.copy()

    recent_hist["meters_expected_adj"] = recent_hist["meters_expected"].replace(0, 1)
    recent_hist["loss_rate"] = 1.0 - (recent_hist["meters_read"] / recent_hist["meters_expected_adj"]).clip(0.0, 1.0)
    recent_hist["unread_meters"] = (recent_hist["meters_expected"] - recent_hist["meters_read"]).clip(lower=0)

    # Summary features
    agg_df = recent_hist.groupby("gateway_id").agg(
        avg_loss_rate=("loss_rate", "mean"),
        avg_unread_meters=("unread_meters", "mean"),
        max_unread_meters=("unread_meters", "max"),
        weeks_recorded=("week_start_date", "nunique"),
    ).reset_index()

    # Most recent week's loss rate
    latest_week = recent_hist.sort_values("week_start_date").groupby("gateway_id").last().reset_index()
    latest_map = latest_week.set_index("gateway_id")["loss_rate"]
    agg_df["last_loss_rate"] = agg_df["gateway_id"].map(latest_map).fillna(0.0)

    return agg_df


def compute_field_visit_features(
    field_visits_df: pd.DataFrame,
    target_monday: dt.date,
) -> pd.DataFrame:
    """Extract technician visit history strictly prior to target_monday."""
    if field_visits_df.empty or "visited_on_date" not in field_visits_df.columns:
        return pd.DataFrame(columns=["gateway_id", "total_past_visits", "days_since_last_visit", "had_recent_visit"])

    hist = field_visits_df[field_visits_df["visited_on_date"] < target_monday].copy()
    if hist.empty:
        return pd.DataFrame(columns=["gateway_id", "total_past_visits", "days_since_last_visit", "had_recent_visit"])

    agg = hist.groupby("gateway_id").agg(
        total_past_visits=("visit_id", "count"),
        last_visit_date=("visited_on_date", "max"),
    ).reset_index()

    agg["days_since_last_visit"] = agg["last_visit_date"].apply(
        lambda d: (target_monday - d).days if pd.notna(d) else 999
    )
    # Had visit within last 14 days (potential resolution or cooling period)
    agg["had_recent_visit"] = (agg["days_since_last_visit"] <= 14).astype(int)

    return agg[["gateway_id", "total_past_visits", "days_since_last_visit", "had_recent_visit"]]


def assemble_feature_matrix(
    target_monday: dt.date,
    gateway_master_df: pd.DataFrame,
    telemetry_df: pd.DataFrame,
    meter_read_df: Optional[pd.DataFrame] = None,
    field_visits_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Assemble an integrated feature matrix per active gateway for target_monday.
    
    Combines:
    - Master register: n_meters_installed, site_type, antenna_type, fw_version
    - Telemetry: 3-sigma anomaly count, offline duration, disconnects, reboots
    - Meter reading: loss rates and unread meter impact
    - Field visits: historic visit count and recency
    """
    # 1. Base from active gateway master
    active_master = gateway_master_df.copy()
    if "gateway_id" not in active_master.columns:
        raise ValueError("gateway_master_df must contain gateway_id")

    base = active_master[["gateway_id", "n_meters_installed", "site_type", "region", "hw_model", "antenna_type"]].copy()

    # 2. Telemetry features
    telem_feats = compute_telemetry_features(telemetry_df, target_monday)
    merged = base.merge(telem_feats, on="gateway_id", how="left")

    # Fill default zeros for gateways with no recent anomalies
    merged["flagged_hours"] = merged["flagged_hours"].fillna(0.0)
    merged["worst_metric"] = merged["worst_metric"].fillna("none")
    merged["recent_offline_hours"] = merged["recent_offline_hours"].fillna(0.0)
    merged["recent_disconnections"] = merged["recent_disconnections"].fillna(0.0)
    merged["recent_reboots"] = merged["recent_reboots"].fillna(0.0)

    # 3. Meter reading features
    if meter_read_df is not None and not meter_read_df.empty:
        mr_feats = compute_meter_read_features(meter_read_df, target_monday)
        merged = merged.merge(mr_feats, on="gateway_id", how="left")
        merged["avg_loss_rate"] = merged["avg_loss_rate"].fillna(0.0)
        merged["last_loss_rate"] = merged["last_loss_rate"].fillna(0.0)
        merged["avg_unread_meters"] = merged["avg_unread_meters"].fillna(0.0)
    else:
        merged["avg_loss_rate"] = 0.0
        merged["last_loss_rate"] = 0.0
        merged["avg_unread_meters"] = 0.0

    # 4. Field visits features
    if field_visits_df is not None and not field_visits_df.empty:
        fv_feats = compute_field_visit_features(field_visits_df, target_monday)
        merged = merged.merge(fv_feats, on="gateway_id", how="left")
        merged["total_past_visits"] = merged["total_past_visits"].fillna(0)
        merged["days_since_last_visit"] = merged["days_since_last_visit"].fillna(999)
        merged["had_recent_visit"] = merged["had_recent_visit"].fillna(0)
    else:
        merged["total_past_visits"] = 0
        merged["days_since_last_visit"] = 999
        merged["had_recent_visit"] = 0

    # Business risk exposure: unread / vulnerable meters
    # Meter scale factor normalized against max meters (~900)
    meter_scale = merged["n_meters_installed"] / 900.0
    merged["meters_at_risk"] = merged["n_meters_installed"] * merged["last_loss_rate"].clip(lower=0.05)

    return merged
