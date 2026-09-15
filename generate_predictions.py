"""CLI script to generate official predictions.csv across all 8 scored weeks."""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import pandas as pd

from app.data.loader import DataLoader, DEFAULT_DATA_DIR
from app.ranking.baseline import ThreeSigmaRanker
from app.ranking.cost_aware import CostRiskRanker
from app.ranking.interface import BaseRanker

SCORED_WEEKS = [dt.date(2026, 2, 2) + dt.timedelta(days=7 * i) for i in range(8)]


def generate_predictions(
    data_dir: pathlib.Path,
    out_path: pathlib.Path,
    ranker_name: str = "baseline",
) -> pd.DataFrame:
    """Generate predictions for the 8 scored weeks and write to out_path."""
    loader = DataLoader(data_dir=data_dir)
    print(f"Loading master and telemetry from: {loader.data_dir}")

    gateway_master = loader.load_gateway_master(active_only=True)
    meter_read_df = loader.load_meter_read_success()
    field_visits_df = loader.load_field_visits()

    # Determine earliest needed date for telemetry: 28 days before first week
    earliest_date = SCORED_WEEKS[0] - dt.timedelta(days=28)
    latest_date = SCORED_WEEKS[-1]
    print(f"Loading telemetry window: {earliest_date} to {latest_date}...")
    telemetry_df = loader.load_telemetry(
        start_date=earliest_date,
        end_date=latest_date,
        columns=["offline_duration_sec", "disconnection_cnt", "reboot_cnt"],
    )
    print(f"Telemetry loaded: {len(telemetry_df)} rows across {telemetry_df['gateway_id'].nunique()} gateways.")

    # Select ranker
    ranker: BaseRanker
    if ranker_name.lower() in ["cost", "cost_risk", "cost-risk"]:
        ranker = CostRiskRanker()
    else:
        ranker = ThreeSigmaRanker()

    print(f"Executing ranking with: {ranker.name}")
    all_weeks_preds = []
    for monday in SCORED_WEEKS:
        ranked_week = ranker.rank_week(
            monday=monday,
            telemetry_df=telemetry_df,
            gateway_master_df=gateway_master,
            top_n=15,
            meter_read_df=meter_read_df,
            field_visits_df=field_visits_df,
        )
        if len(ranked_week) != 15:
            raise ValueError(f"Week {monday} produced {len(ranked_week)} recommendations, expected 15.")
        all_weeks_preds.append(ranked_week)

    final_df = pd.concat(all_weeks_preds, ignore_index=True)
    required_cols = ["week_start", "rank", "gateway_id", "score", "reason"]
    final_df = final_df[required_cols]

    final_df.to_csv(out_path, index=False)
    print(f"Wrote {len(final_df)} rows to {out_path} ({final_df['week_start'].nunique()} weeks).")
    return final_df


def main():
    parser = argparse.ArgumentParser(description="Generate LPDG challenge predictions.csv")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=DEFAULT_DATA_DIR,
        help="Path to data directory (default: 03-challenge-data/data)",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("predictions.csv"),
        help="Output CSV path (default: predictions.csv)",
    )
    parser.add_argument(
        "--ranker",
        type=str,
        default="baseline",
        choices=["baseline", "cost_risk"],
        help="Ranking strategy to use (default: baseline)",
    )
    args = parser.parse_args()

    generate_predictions(data_dir=args.data, out_path=args.out, ranker_name=args.ranker)


if __name__ == "__main__":
    main()
