"""Unit and integration tests for data loading, processing, and validation."""

import datetime as dt
import pathlib
import tempfile
import unittest
import pandas as pd

from app.data.processor import (
    normalize_gateway_id,
    filter_active_gateways,
    read_csv_resilient,
    validate_columns,
    InvalidGatewayIdError,
    DataValidationError,
)
from app.data.loader import (
    DataLoader,
    DataDirectoryNotFoundError,
    DatasetNotFoundError,
    PackageMissingError,
)


class TestGatewayProcessor(unittest.TestCase):
    """Test gateway ID normalization and active filtering."""

    def test_normalize_valid_ids(self):
        # Colon-separated MAC
        self.assertEqual(normalize_gateway_id("06:39:EA:56:02:C1"), "0639EA5602C1")
        self.assertEqual(normalize_gateway_id("0a:56:03:8b:20:d0"), "0A56038B20D0")
        # Bare 12-hex
        self.assertEqual(normalize_gateway_id("0202cb0a6b1f"), "0202CB0A6B1F")
        self.assertEqual(normalize_gateway_id("0202CB0A6B1F"), "0202CB0A6B1F")

    def test_normalize_invalid_ids_lenient(self):
        self.assertIsNone(normalize_gateway_id("invalid-id"))
        self.assertIsNone(normalize_gateway_id("123"))
        self.assertIsNone(normalize_gateway_id(None))

    def test_normalize_invalid_ids_strict(self):
        with self.assertRaises(InvalidGatewayIdError):
            normalize_gateway_id("invalid-id", strict=True)
        with self.assertRaises(InvalidGatewayIdError):
            normalize_gateway_id(None, strict=True)

    def test_filter_active_gateways(self):
        df = pd.DataFrame({
            "gateway_id": ["GW0000000001", "GW0000000002", "GW0000000003", "GW0000000004"],
            "decommissioned_on": [None, "2025-11-20", "", "nan"],
        })
        filtered = filter_active_gateways(df)
        self.assertEqual(len(filtered), 3)
        self.assertNotIn("GW0000000002", filtered["gateway_id"].values)
        self.assertIn("GW0000000001", filtered["gateway_id"].values)
        # Original df must be untouched
        self.assertEqual(len(df), 4)

    def test_read_csv_resilient_latin1(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".csv") as tmp:
            # Write Latin-1 German text ("Außenmast")
            tmp.write("gateway_id,site_type\n0639EA5602C1,Außenmast\n".encode("latin1"))
            tmp_path = tmp.name

        try:
            df = read_csv_resilient(tmp_path, required_columns=["gateway_id", "site_type"])
            self.assertEqual(len(df), 1)
            self.assertEqual(df.loc[0, "site_type"], "Außenmast")
        finally:
            pathlib.Path(tmp_path).unlink(missing_ok=True)

    def test_validate_columns_missing(self):
        df = pd.DataFrame({"col_a": [1, 2]})
        with self.assertRaises(DataValidationError):
            validate_columns(df, ["col_a", "missing_col"], "test_dataset")


class TestDataLoader(unittest.TestCase):
    """Test DataLoader configuration and error handling."""

    def test_missing_data_directory(self):
        with self.assertRaises(DataDirectoryNotFoundError):
            DataLoader(data_dir="non_existent_directory_xyz_123")

    def test_missing_dataset_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            loader = DataLoader(data_dir=tmp_dir)
            with self.assertRaises(DatasetNotFoundError):
                loader.load_gateway_master()


if __name__ == "__main__":
    unittest.main()
