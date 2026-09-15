"""Unit and integration tests for Web API endpoints and error handling."""

import unittest
import pandas as pd
from app.main import create_app
from app.ranking.interface import BaseRanker


class MockCustomRanker(BaseRanker):
    """Mock ranker to verify algorithm swapping without API changes."""
    @property
    def name(self) -> str:
        return "mock_custom_ranker"

    def rank_week(self, monday, telemetry_df, gateway_master_df, top_n=15, **kwargs):
        return pd.DataFrame([
            {
                "week_start": monday.isoformat(),
                "rank": 1,
                "gateway_id": "0639EA5602C1",
                "score": 99.9,
                "reason": "Mock diagnostic reason",
            }
        ])

    def explain_gateway(self, monday, gateway_id, telemetry_df, gateway_master_df, **kwargs):
        return {"gateway_id": gateway_id, "score": 99.9, "rank": 1, "reason": "Mock explanation"}


class TestApiEndpoints(unittest.TestCase):
    """Test API route responses, status codes, and input validation."""

    def setUp(self):
        self.app = create_app(load_data=False)
        self.app.config["TESTING"] = True
        self.app.config["GATEWAY_MASTER_DF"] = pd.DataFrame({
            "gateway_id": ["0639EA5602C1"],
            "tenant": ["tenant_a"],
            "site_type": ["Außenmast"],
            "region": ["Niedersachsen"],
            "hw_model": ["GW-2100"],
            "antenna_type": ["Omni 3dBi"],
            "fw_version": ["3.3.1"],
            "installed_on": ["2023-06-19"],
            "n_meters_installed": [113],
        })
        self.app.config["TELEMETRY_DF"] = pd.DataFrame({
            "gateway_id": ["0639EA5602C1"],
            "ts": [pd.Timestamp("2026-01-20 00:00:00", tz="UTC")],
            "offline_duration_sec": [100],
            "disconnection_cnt": [1],
            "reboot_cnt": [0],
        })
        self.client = self.app.test_client()

    def test_index_route(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("LPDG Gateway Risk Dashboard", response.get_data(as_text=True))

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertIn(response.status_code, [200, 503])
        data = response.get_json()
        self.assertIn("status", data)
        self.assertEqual(data["service"], "lpdg-gateway-maintenance")

    def test_predictions_missing_param(self):
        response = self.client.get("/api/predictions")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing required query parameter", response.get_json()["error"])

    def test_predictions_invalid_date_format(self):
        response = self.client.get("/api/predictions?week=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid date format", response.get_json()["error"])

    def test_predictions_not_a_monday(self):
        # 2026-02-03 is Tuesday
        response = self.client.get("/api/predictions?week=2026-02-03")
        self.assertEqual(response.status_code, 400)
        self.assertIn("is not a Monday", response.get_json()["error"])

    def test_predictions_success(self):
        response = self.client.get("/api/predictions?week=2026-02-02")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["week_start"], "2026-02-02")
        self.assertIn("recommendations", data)

    def test_gateway_lookup_valid(self):
        response = self.client.get("/api/gateways/06:39:EA:56:02:C1")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["gateway_id"], "0639EA5602C1")
        self.assertEqual(data["hw_model"], "GW-2100")

    def test_gateway_lookup_invalid_id(self):
        response = self.client.get("/api/gateways/invalid-mac")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid gateway ID format", response.get_json()["error"])

    def test_gateway_lookup_not_found(self):
        response = self.client.get("/api/gateways/FFFFFFFFFFFF")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found in registry", response.get_json()["error"])

    def test_explain_gateway(self):
        response = self.client.get("/api/gateways/06:39:EA:56:02:C1/explain?week=2026-02-02")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["gateway_id"], "0639EA5602C1")
        self.assertIn("score", data)

    def test_swappable_ranker(self):
        """Verify that a different ranker can be injected without altering API code."""
        custom_app = create_app(ranker=MockCustomRanker(), load_data=False)
        custom_app.config["TESTING"] = True
        custom_app.config["GATEWAY_MASTER_DF"] = self.app.config["GATEWAY_MASTER_DF"]
        custom_app.config["TELEMETRY_DF"] = self.app.config["TELEMETRY_DF"]

        with custom_app.test_client() as client:
            resp = client.get("/api/predictions?week=2026-02-02")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["ranker"], "mock_custom_ranker")
            self.assertEqual(len(data["recommendations"]), 1)
            self.assertEqual(data["recommendations"][0]["score"], 99.9)


if __name__ == "__main__":
    unittest.main()
