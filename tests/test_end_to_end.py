"""End-to-end pipeline and regression test suite."""

import datetime as dt
import unittest
import pandas as pd

from app.data.loader import DataLoader
from app.data.processor import normalize_gateway_id, filter_active_gateways
from app.ranking.baseline import ThreeSigmaRanker
from app.ranking.cost_aware import CostRiskRanker


class TestEndToEndPipeline(unittest.TestCase):
    """End-to-end integration and bug regression tests."""

    def test_end_to_end_ranking_pipeline(self):
        """End-to-end test verifying full ranking output schema compliance."""
        ranker = ThreeSigmaRanker()
        monday = dt.date(2026, 2, 2)

        master_df = pd.DataFrame({
            "gateway_id": [f"00000000000{i}" for i in range(1, 6)],
            "decommissioned_on": [None] * 5,
        })

        # Generate synthetic observations
        records = []
        for day in range(28):
            current_ts = pd.Timestamp(monday, tz="UTC") - dt.timedelta(days=28 - day)
            for i in range(1, 6):
                # Gateway 1 has steady baseline (std ~ 1) and sudden extreme spike on recent days
                is_anomaly = (i == 1 and day >= 26)
                records.append({
                    "gateway_id": f"00000000000{i}",
                    "ts": current_ts,
                    "offline_duration_sec": 50000 if is_anomaly else (10 + (day % 3)),
                    "disconnection_cnt": 100 if is_anomaly else (1 + (day % 2)),
                    "reboot_cnt": 50 if is_anomaly else (day % 2),
                })

        telemetry_df = pd.DataFrame(records)
        predictions = ranker.rank_week(monday, telemetry_df, master_df, top_n=5)

        self.assertEqual(len(predictions), 5)
        self.assertEqual(list(predictions["rank"]), [1, 2, 3, 4, 5])
        # Gateway 1 had huge anomaly in last 7 days and should be ranked 1st
        self.assertEqual(predictions.iloc[0]["gateway_id"], "000000000001")
        self.assertGreater(predictions.iloc[0]["score"], 0)

    def test_bug_regression_decommissioned_gateway_not_recommended(self):
        """Regression test: A decommissioned gateway must NEVER be recommended for field visits.
        
        Bug found during Phase 1 inspection: Gateways with decommissioned_on populated
        in gateway_master.csv would otherwise be selected by the 3-sigma ranker if their
        past telemetry showed anomalies, wasting €380 per visit.
        """
        ranker = ThreeSigmaRanker()
        monday = dt.date(2026, 2, 2)

        master_df = pd.DataFrame({
            "gateway_id": ["000000000001", "000000000002"],
            "decommissioned_on": ["2026-01-15", None],
        })

        timestamps = [pd.Timestamp("2026-01-30", tz="UTC")]
        telemetry_df = pd.DataFrame({
            "gateway_id": ["000000000001", "000000000002"],
            "ts": timestamps * 2,
            "offline_duration_sec": [10000, 10],
            "disconnection_cnt": [50, 1],
            "reboot_cnt": [20, 0],
        })

        predictions = ranker.rank_week(monday, telemetry_df, master_df, top_n=2)
        recommended_ids = list(predictions["gateway_id"])

        self.assertNotIn("000000000001", recommended_ids)
        self.assertIn("000000000002", recommended_ids)

    def test_official_data_end_to_end_integration(self):
        """Integration test with official challenge data for a scored Monday."""
        loader = DataLoader()
        master_df = loader.load_gateway_master(active_only=True)
        monday = dt.date(2026, 2, 2)
        telemetry_df = loader.load_telemetry(
            start_date=monday - dt.timedelta(days=28),
            end_date=monday,
            columns=["offline_duration_sec", "disconnection_cnt", "reboot_cnt"],
        )

        ranker = ThreeSigmaRanker()
        preds = ranker.rank_week(monday, telemetry_df, master_df, top_n=15)

        self.assertEqual(len(preds), 15)
        self.assertEqual(list(preds["rank"]), list(range(1, 16)))
        # No duplicates
        self.assertEqual(len(set(preds["gateway_id"])), 15)
        # All reasons <= 300 chars
        for reason in preds["reason"]:
            self.assertLessEqual(len(reason), 300)


if __name__ == "__main__":
    unittest.main()
