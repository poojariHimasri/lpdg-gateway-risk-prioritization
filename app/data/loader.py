"""Configurable data loader for LPDG challenge datasets with validation and resilience."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
from typing import Any, Dict, List, Optional, Union
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from app.data.processor import (
    DataValidationError,
    InvalidGatewayIdError,
    filter_active_gateways,
    normalize_gateway_id,
    read_csv_resilient,
    validate_columns,
)


class DataDirectoryNotFoundError(FileNotFoundError):
    """Raised when the configured data directory cannot be found."""
    pass


class DatasetNotFoundError(FileNotFoundError):
    """Raised when a specific dataset file is missing from the data directory."""
    pass


class PackageMissingError(ImportError):
    """Raised when an optional third-party library is required but not installed."""
    pass


def _resolve_default_data_dir() -> pathlib.Path:
    """Resolve default data directory relative to repository root."""
    proj_root = pathlib.Path(__file__).resolve().parent.parent.parent
    candidate = proj_root / "03-challenge-data" / "data"
    if candidate.exists():
        return candidate
    cwd_candidate = pathlib.Path("03-challenge-data") / "data"
    return cwd_candidate


DEFAULT_DATA_DIR = _resolve_default_data_dir()


class DataLoader:
    """Loads, validates, and standardizes datasets for the LPDG challenge."""

    GATEWAY_MASTER_REQUIRED = [
        "gateway_id",
        "tenant",
        "site_type",
        "region",
        "hw_model",
        "antenna_type",
        "fw_version",
        "installed_on",
        "n_meters_installed",
    ]

    METER_READ_REQUIRED = [
        "week_start",
        "gateway_id",
        "meters_expected",
        "meters_read",
    ]

    FIELD_VISITS_REQUIRED = [
        "visit_id",
        "gateway_id",
        "requested_on",
        "visited_on",
        "reason_reported",
        "outcome",
        "parts_replaced",
        "technician_hours",
    ]

    ENGINEER_REVIEW_REQUIRED = [
        "gateway_id",
        "standort",
        "Kategorie",
        "reviewed_on",
        "reviewer",
        "Bemerkung",
    ]

    def __init__(self, data_dir: Optional[Union[str, pathlib.Path]] = None) -> None:
        """Initialize DataLoader with an optional explicit data directory path."""
        if data_dir is not None:
            self.data_dir = pathlib.Path(data_dir)
        else:
            env_val = os.environ.get("LPDG_DATA_DIR")
            if env_val:
                self.data_dir = pathlib.Path(env_val)
            else:
                self.data_dir = _resolve_default_data_dir()

        if not self.data_dir.exists():
            raise DataDirectoryNotFoundError(
                f"Data directory not found at: '{self.data_dir}'. "
                "Ensure '03-challenge-data/data' exists or set the LPDG_DATA_DIR environment variable."
            )

    def _get_dataset_path(self, filename: str) -> pathlib.Path:
        """Locate a dataset file inside data_dir and verify existence."""
        p = self.data_dir / filename
        if not p.exists():
            raise DatasetNotFoundError(
                f"Required dataset '{filename}' not found in data directory: '{self.data_dir}'."
            )
        return p

    def load_gateway_master(
        self, active_only: bool = True, strict_ids: bool = False
    ) -> pd.DataFrame:
        """Load and validate gateway_master.csv.
        
        - Uses resilient UTF-8 / Latin-1 encoding fallback.
        - Preserves German site types and regions.
        - Normalizes gateway IDs to uppercase bare 12-hex format.
        - Filters out decommissioned gateways if active_only=True.
        """
        path = self._get_dataset_path("gateway_master.csv")
        df = read_csv_resilient(
            path,
            required_columns=self.GATEWAY_MASTER_REQUIRED,
            dataset_name="gateway_master.csv",
        )

        df["raw_gateway_id"] = df["gateway_id"]
        normalized_ids = df["gateway_id"].apply(
            lambda gid: normalize_gateway_id(gid, strict=strict_ids)
        )
        if strict_ids and normalized_ids.isna().any():
            invalid_idx = normalized_ids.isna().idxmax()
            raw_val = df.loc[invalid_idx, "raw_gateway_id"]
            raise InvalidGatewayIdError(
                f"gateway_master.csv contains invalid gateway_id: '{raw_val}'"
            )

        df["gateway_id"] = normalized_ids

        # Parse installation and decommission dates
        df["installed_on"] = pd.to_datetime(df["installed_on"], errors="coerce").dt.date
        if "decommissioned_on" in df.columns:
            df["decommissioned_date"] = pd.to_datetime(
                df["decommissioned_on"], errors="coerce"
            ).dt.date

        if active_only:
            df = filter_active_gateways(df)

        return df.reset_index(drop=True)

    def load_meter_read_success(self, strict_ids: bool = False) -> pd.DataFrame:
        """Load and validate meter_read_success.csv.
        
        - Parses week_start as datetime dates.
        - Validates meters_expected and meters_read are non-negative.
        - Normalizes gateway IDs.
        """
        path = self._get_dataset_path("meter_read_success.csv")
        df = read_csv_resilient(
            path,
            required_columns=self.METER_READ_REQUIRED,
            dataset_name="meter_read_success.csv",
        )

        df["raw_gateway_id"] = df["gateway_id"]
        df["gateway_id"] = df["gateway_id"].apply(
            lambda gid: normalize_gateway_id(gid, strict=strict_ids)
        )

        # Parse week_start
        try:
            df["week_start_date"] = pd.to_datetime(df["week_start"]).dt.date
        except Exception as err:
            raise DataValidationError(f"Failed to parse week_start dates in meter_read_success: {err}")

        # Validate integer counts
        if (df["meters_expected"] < 0).any():
            raise DataValidationError("meter_read_success contains negative meters_expected values")
        if (df["meters_read"] < 0).any():
            raise DataValidationError("meter_read_success contains negative meters_read values")

        return df.reset_index(drop=True)

    def load_field_visits(self, strict_ids: bool = False) -> pd.DataFrame:
        """Load and validate field_visits.csv.
        
        - Parses requested_on and visited_on as datetime dates.
        - Preserves German text fields (reason_reported, outcome, parts_replaced).
        - Normalizes gateway IDs.
        """
        path = self._get_dataset_path("field_visits.csv")
        df = read_csv_resilient(
            path,
            required_columns=self.FIELD_VISITS_REQUIRED,
            dataset_name="field_visits.csv",
        )

        df["raw_gateway_id"] = df["gateway_id"]
        df["gateway_id"] = df["gateway_id"].apply(
            lambda gid: normalize_gateway_id(gid, strict=strict_ids)
        )

        df["requested_on_date"] = pd.to_datetime(df["requested_on"], errors="coerce").dt.date
        df["visited_on_date"] = pd.to_datetime(df["visited_on"], errors="coerce").dt.date

        return df.reset_index(drop=True)

    def load_engineer_review(
        self, sheet_name: str = "Gateway Status", strict_ids: bool = False
    ) -> pd.DataFrame:
        """Load engineer_review_2026-02.xlsx.
        
        - Loads the specified sheet ('Gateway Status').
        - Parses reviewed_on date.
        - Preserves Kategorie ('Normal' / 'Schlecht') and German Bemerkung notes.
        - Works with openpyxl if installed, or falls back to built-in pure-Python XML parser.
        """
        path = self._get_dataset_path("engineer_review_2026-02.xlsx")

        df = None
        # 1. Attempt using pandas read_excel if openpyxl/calamine is installed
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, engine=None)
        except Exception:
            # 2. Fall back to standard-library XML extraction from the xlsx zip container
            df = self._load_xlsx_fallback(path, sheet_name=sheet_name)

        if df is None:
            raise PackageMissingError(
                "Neither openpyxl nor fallback parser could read engineer_review_2026-02.xlsx."
            )

        validate_columns(df, self.ENGINEER_REVIEW_REQUIRED, "engineer_review_2026-02.xlsx")

        df["raw_gateway_id"] = df["gateway_id"]
        df["gateway_id"] = df["gateway_id"].apply(
            lambda gid: normalize_gateway_id(gid, strict=strict_ids)
        )

        # Parse reviewed_on (handling Excel serial date e.g. 46068 or date string)
        def _parse_reviewed_date(v: Any) -> Optional[dt.date]:
            if pd.isna(v) or str(v).strip() == "":
                return None
            val_str = str(v).strip()
            # Try float/int Excel serial date
            try:
                num = float(val_str)
                # Excel base date is 1899-12-30
                return (dt.date(1899, 12, 30) + dt.timedelta(days=int(num)))
            except ValueError:
                pass
            # Try ISO or standard date parsing
            try:
                return pd.to_datetime(val_str).date()
            except Exception:
                return None

        df["reviewed_on_date"] = df["reviewed_on"].apply(_parse_reviewed_date)

        return df.reset_index(drop=True)

    def _load_xlsx_fallback(
        self, path: pathlib.Path, sheet_name: str = "Gateway Status"
    ) -> pd.DataFrame:
        """Pure-Python standard-library parser for xlsx without requiring external packages."""
        try:
            with zipfile.ZipFile(path, "r") as z:
                # Find sheet r:id matching sheet_name
                wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
                ns = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                sheets = wb_xml.findall(".//ns:sheet", ns)
                target_sheet_file = "xl/worksheets/sheet1.xml"  # default first sheet
                for idx, s in enumerate(sheets, start=1):
                    if s.attrib.get("name") == sheet_name:
                        target_sheet_file = f"xl/worksheets/sheet{idx}.xml"
                        break

                sheet_xml = ET.fromstring(z.read(target_sheet_file))
                rows_data = []
                for row_el in sheet_xml.findall(".//ns:row", ns):
                    row_vals: Dict[str, str] = {}
                    for c_el in row_el.findall(".//ns:c", ns):
                        cell_ref = c_el.attrib.get("r", "")
                        col_letters = "".join(ch for ch in cell_ref if ch.isalpha())
                        # Check inline string or value
                        val = ""
                        t_el = c_el.find(".//ns:t", ns)
                        if t_el is not None and t_el.text:
                            val = t_el.text
                        else:
                            v_el = c_el.find(".//ns:v", ns)
                            if v_el is not None and v_el.text:
                                val = v_el.text
                        row_vals[col_letters] = val
                    rows_data.append(row_vals)

                if not rows_data:
                    return pd.DataFrame()

                # Deduce columns from header row
                header_row = rows_data[0]
                cols_ordered = sorted(header_row.keys())
                headers = [header_row[k] for k in cols_ordered]

                parsed_records = []
                for r in rows_data[1:]:
                    parsed_records.append([r.get(k, "") for k in cols_ordered])

                return pd.DataFrame(parsed_records, columns=headers)
        except Exception as err:
            raise DataValidationError(f"Fallback xlsx parser failed: {err}") from err

    def list_telemetry_partitions(self) -> List[str]:
        """Return a sorted list of available telemetry month partition names."""
        telemetry_dir = self.data_dir / "telemetry"
        if not telemetry_dir.exists():
            raise DatasetNotFoundError(f"Telemetry folder not found at: '{telemetry_dir}'")

        partitions = [
            p.name
            for p in sorted(telemetry_dir.iterdir())
            if p.is_dir() and p.name.startswith("month=")
        ]
        return partitions

    def load_telemetry(
        self,
        start_date: Optional[Union[dt.date, str]] = None,
        end_date: Optional[Union[dt.date, str]] = None,
        months: Optional[List[str]] = None,
        columns: Optional[List[str]] = None,
        strict_ids: bool = False,
    ) -> pd.DataFrame:
        """Load telemetry partitioned Parquet data with windowing and memory optimization.
        
        Parameters:
        -----------
        start_date: Optional start date filter (inclusive).
        end_date: Optional end date filter (exclusive).
        months: Explicit list of partition names (e.g. ['2025-08', '2025-09'] or ['month=2025-08']).
        columns: Specific telemetry columns to project. Preserves bandwidth and memory.
        strict_ids: Whether to raise InvalidGatewayIdError on malformed IDs.
        """
        telemetry_dir = self.data_dir / "telemetry"
        if not telemetry_dir.exists():
            raise DatasetNotFoundError(f"Telemetry directory not found at: '{telemetry_dir}'")

        available_partitions = self.list_telemetry_partitions()
        if not available_partitions:
            raise DatasetNotFoundError("No 'month=YYYY-MM' partitions found inside telemetry directory.")

        # Determine target partitions to avoid reading unneeded months
        target_partitions = available_partitions
        if months:
            formatted_months = {m if m.startswith("month=") else f"month={m}" for m in months}
            target_partitions = [p for p in available_partitions if p in formatted_months]

        elif start_date or end_date:
            s_date = (
                pd.to_datetime(start_date).date() if start_date else dt.date(2000, 1, 1)
            )
            e_date = (
                pd.to_datetime(end_date).date() if end_date else dt.date(2099, 12, 31)
            )
            filtered = []
            for p in available_partitions:
                # p is 'month=YYYY-MM'
                m_str = p.replace("month=", "")
                try:
                    p_year, p_month = map(int, m_str.split("-"))
                    p_start = dt.date(p_year, p_month, 1)
                    # Next month start
                    next_month = p_month + 1 if p_month < 12 else 1
                    next_year = p_year if p_month < 12 else p_year + 1
                    p_end = dt.date(next_year, next_month, 1)
                    if not (p_end <= s_date or p_start >= e_date):
                        filtered.append(p)
                except ValueError:
                    filtered.append(p)
            target_partitions = filtered

        # Project columns ensuring gateway_id and ts_utc are present
        proj_cols = None
        if columns:
            needed = {"gateway_id", "ts_utc"}
            proj_cols = list(needed.union(columns))

        # Check for parquet engine availability
        frames = []
        for part in target_partitions:
            part_path = telemetry_dir / part
            try:
                part_df = pd.read_parquet(part_path, columns=proj_cols)
                frames.append(part_df)
            except ImportError as err:
                raise PackageMissingError(
                    "Parquet reader unavailable. Please install 'pyarrow' or 'fastparquet' to read the telemetry partitioned parquet dataset."
                ) from err
            except Exception as err:
                # If reading parquet directly failed due to engine
                err_msg = str(err).lower()
                if "engine" in err_msg or "pyarrow" in err_msg or "fastparquet" in err_msg:
                    raise PackageMissingError(
                        "Parquet reader unavailable. Please install 'pyarrow' or 'fastparquet' to read the telemetry partitioned parquet dataset."
                    ) from err
                raise DataValidationError(f"Failed to read parquet partition '{part}': {err}") from err

        if not frames:
            return pd.DataFrame(columns=proj_cols if proj_cols else ["gateway_id", "ts_utc"])

        df = pd.concat(frames, ignore_index=True)
        df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)
        df["raw_gateway_id"] = df["gateway_id"]
        df["gateway_id"] = df["gateway_id"].apply(
            lambda gid: normalize_gateway_id(gid, strict=strict_ids)
        )

        # Apply exact timestamp bounds if requested
        if start_date:
            start_ts = pd.Timestamp(start_date, tz="UTC")
            df = df[df["ts"] >= start_ts]
        if end_date:
            end_ts = pd.Timestamp(end_date, tz="UTC")
            df = df[df["ts"] < end_ts]

        return df.reset_index(drop=True)
