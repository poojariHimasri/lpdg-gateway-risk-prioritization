"""Tests for gateway normalization and active status filtering."""

import unittest
import pandas as pd
from app.data.processor import (
    normalize_gateway_id,
    filter_active_gateways,
    InvalidGatewayIdError,
)


class TestGatewayProcessor(unittest.TestCase):
    """Test normalization of gateway MACs and filtering of decommissioned units."""

    def test_normalize_gateway_id_colon_format(self):
        self.assertEqual(normalize_gateway_id("06:39:EA:56:02:C1"), "0639EA5602C1")
        self.assertEqual(normalize_gateway_id("0a:56:03:8b:20:d0"), "0A56038B20D0")

    def test_normalize_gateway_id_bare_format(self):
        self.assertEqual(normalize_gateway_id("0202cb0a6b1f"), "0202CB0A6B1F")
        self.assertEqual(normalize_gateway_id("0202CB0A6B1F"), "0202CB0A6B1F")

    def test_normalize_gateway_id_invalid(self):
        self.assertIsNone(normalize_gateway_id("INVALID_ID"))
        self.assertIsNone(normalize_gateway_id("12345"))
        self.assertIsNone(normalize_gateway_id(None))

    def test_normalize_gateway_id_strict(self):
        with self.assertRaises(InvalidGatewayIdError):
            normalize_gateway_id("invalid-id", strict=True)

    def test_filter_active_gateways(self):
        data = {
            "gateway_id": ["0639EA5602C1", "0A56038B20D0", "0E5DFCF65AD4"],
            "decommissioned_on": [None, "2025-10-15", ""],
        }
        df = pd.DataFrame(data)
        active = filter_active_gateways(df)
        self.assertEqual(len(active), 2)
        self.assertNotIn("0A56038B20D0", active["gateway_id"].values)
        self.assertIn("0639EA5602C1", active["gateway_id"].values)
        self.assertIn("0E5DFCF65AD4", active["gateway_id"].values)


if __name__ == "__main__":
    unittest.main()
