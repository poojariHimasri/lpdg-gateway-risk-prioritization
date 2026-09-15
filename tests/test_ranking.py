"""Tests for ranking algorithms and pluggable ranker contracts."""

import datetime as dt
import unittest
import pandas as pd

from app.ranking.baseline import ThreeSigmaRanker
from app.ranking.cost_aware import CostRiskRanker
from app.ranking.interface import BaseRanker


class TestRankingStrategies(unittest.TestCase):
    """Test baseline and cost-aware ranking implementations."""

    def setUp(self):
        self.monday = dt.date(2026, 2, 2)
        self.master_df = pd.DataFrame({
            "gateway_id": ["000000000001", "000000000002", "000000000003"],
            "n_meters_installed": [150, 600, 300],
            "site_type": ["Außenmast", "Schaltschrank", "Heizraum"],
            "region": ["Bayern", "Niedersachsen", "Hessen"],
            "hw_model": ["GW-2100", "GW-2100", "GW-2100"],
            "antenna_type": ["Omni 3dBi", "Omni 5dBi", "Yagi 9dBi"],
            "decommissioned_on": [None, None, "2025-12-01"],
        })
        end_ts = pd.Timestamp(self.monday, tz="UTC")
        self.telemetry_df = pd.DataFrame([
            {
                "gateway_id": "000000000001",
                "ts": end_ts - dt.timedelta(days=2),
                "offline_duration_sec": 7200,
                "disconnection_cnt": 15,
                "reboot_cnt": 5,
            },
            {
                "gateway_id": "000000000002",
                "ts": end_ts - dt.timedelta(days=1),
                "offline_duration_sec": 14400,
                "disconnection_cnt": 30,
                "reboot_cnt": 10,
            },
            {
                "gateway_id": "000000000003",  # decommissioned
                "ts": end_ts - dt.timedelta(days=1),
                "offline_duration_sec": 30000,
                "disconnection_cnt": 50,
                "reboot_cnt": 20,
            }
        ])

    def test_three_sigma_ranker(self):
        ranker = ThreeSigmaRanker()
        self.assertEqual(ranker.name, "baseline_3sigma")
        ranked = ranker.rank_week(self.monday, self.telemetry_df, self.master_df, top_n=2)

        self.assertIsInstance(ranked, pd.DataFrame)
        self.assertEqual(list(ranked["rank"]), [1, 2])
        # Decommissioned gateway 3 must NOT be present
        self.assertNotIn("000000000003", ranked["gateway_id"].values)
        # Reason <= 300 chars
        for reason in ranked["reason"]:
            self.assertLessEqual(len(reason), 300)

    def test_cost_risk_ranker(self):
        ranker = CostRiskRanker()
        self.assertEqual(ranker.name, "cost_risk_ranker")
        ranked = ranker.rank_week(self.monday, self.telemetry_df, self.master_df, top_n=2)

        self.assertIsInstance(ranked, pd.DataFrame)
        self.assertEqual(list(ranked["rank"]), [1, 2])
        # Decommissioned gateway 3 must NOT be present
        self.assertNotIn("000000000003", ranked["gateway_id"].values)
        # Gateway 2 has higher meter count (600 vs 150) and higher outages, so should be ranked 1st
        self.assertEqual(ranked.iloc[0]["gateway_id"], "000000000002")
        for reason in ranked["reason"]:
            self.assertLessEqual(len(reason), 300)

    def test_explain_gateway(self):
        ranker = CostRiskRanker()
        explanation = ranker.explain_gateway(
            self.monday, "000000000002", self.telemetry_df, self.master_df
        )
        self.assertEqual(explanation["gateway_id"], "000000000002")
        self.assertIsNotNone(explanation["rank"])
        self.assertGreater(explanation["score"], 0)


if __name__ == "__main__":
    unittest.main()
