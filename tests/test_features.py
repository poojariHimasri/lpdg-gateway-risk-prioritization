"""Unit tests for feature engineering module."""

import datetime as dt
import unittest
import pandas as pd

from app.features.engineering import (
    compute_telemetry_features,
    compute_meter_read_features,
    compute_field_visit_features,
    assemble_feature_matrix,
)


class TestFeatureEngineering(unittest.TestCase):
    """Test feature calculation from telemetry, meter reads, and field visits."""

    def setUp(self):
        self.target_monday = dt.date(2026, 2, 2)
        self.gateway_master = pd.DataFrame({
            "gateway_id": ["0639EA5602C1", "0A56038B20D0"],
            "n_meters_installed": [200, 450],
            "site_type": ["Außenmast", "Schaltschrank"],
            "region": ["Niedersachsen", "Bayern"],
            "hw_model": ["GW-2100", "GW-2100"],
            "antenna_type": ["Omni 3dBi", "Omni 5dBi"],
        })

    def test_compute_telemetry_features_empty(self):
        empty_telem = pd.DataFrame(columns=["gateway_id", "ts", "offline_duration_sec", "disconnection_cnt", "reboot_cnt"])
        feats = compute_telemetry_features(empty_telem, self.target_monday)
        self.assertTrue(feats.empty)

    def test_compute_telemetry_features_with_data(self):
        end_ts = pd.Timestamp(self.target_monday, tz="UTC")
        timestamps = [end_ts - dt.timedelta(days=i) for i in range(1, 25)]
        records = []
        for ts in timestamps:
            records.append({
                "gateway_id": "0639EA5602C1",
                "ts": ts,
                "offline_duration_sec": 3600 if ts >= end_ts - dt.timedelta(days=5) else 100,
                "disconnection_cnt": 10 if ts >= end_ts - dt.timedelta(days=5) else 1,
                "reboot_cnt": 5 if ts >= end_ts - dt.timedelta(days=5) else 0,
            })
        df = pd.DataFrame(records)
        feats = compute_telemetry_features(df, self.target_monday)
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats.loc[0, "gateway_id"], "0639EA5602C1")
        self.assertGreater(feats.loc[0, "recent_offline_hours"], 0)

    def test_compute_meter_read_features(self):
        mr_df = pd.DataFrame({
            "week_start_date": [dt.date(2026, 1, 19), dt.date(2026, 1, 26)],
            "gateway_id": ["0639EA5602C1", "0639EA5602C1"],
            "meters_expected": [100, 100],
            "meters_read": [90, 80],
        })
        feats = compute_meter_read_features(mr_df, self.target_monday)
        self.assertEqual(len(feats), 1)
        self.assertAlmostEqual(feats.loc[0, "avg_loss_rate"], 0.15)
        self.assertAlmostEqual(feats.loc[0, "last_loss_rate"], 0.20)

    def test_assemble_feature_matrix_integration(self):
        end_ts = pd.Timestamp(self.target_monday, tz="UTC")
        telem_df = pd.DataFrame([{
            "gateway_id": "0639EA5602C1",
            "ts": end_ts - dt.timedelta(days=2),
            "offline_duration_sec": 7200,
            "disconnection_cnt": 15,
            "reboot_cnt": 4,
        }])
        matrix = assemble_feature_matrix(
            target_monday=self.target_monday,
            gateway_master_df=self.gateway_master,
            telemetry_df=telem_df,
        )
        self.assertEqual(len(matrix), 2)
        self.assertIn("flagged_hours", matrix.columns)
        self.assertIn("meters_at_risk", matrix.columns)


if __name__ == "__main__":
    unittest.main()
