"""Data processing, gateway normalization, and validation utilities."""

from __future__ import annotations

import io
import os
import pathlib
import re
from typing import Any, List, Optional, Union
import pandas as pd

_BARE_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")
_COLON_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class InvalidGatewayIdError(ValueError):
    """Raised when a gateway ID string is malformed or invalid."""
    pass


class DataValidationError(ValueError):
    """Raised when dataset structure, schema, or content fails validation."""
    pass


def normalize_gateway_id(gateway_id: Any, strict: bool = False) -> Optional[str]:
    """Normalize a gateway ID into an uppercase bare 12-character hexadecimal string.
    
    Accepts:
      - Bare 12-character hexadecimal strings (e.g. '0639ea5602c1' -> '0639EA5602C1')
      - Colon-separated 6-byte hex MAC strings (e.g. '06:39:EA:56:02:C1' -> '0639EA5602C1')

    If strict=True and gateway_id is invalid, raises InvalidGatewayIdError.
    If strict=False and gateway_id is invalid, returns None.
    """
    if gateway_id is None or pd.isna(gateway_id):
        if strict:
            raise InvalidGatewayIdError("Gateway ID is null or missing")
        return None

    val = str(gateway_id).strip()
    if _BARE_PATTERN.match(val):
        return val.upper()
    if _COLON_PATTERN.match(val):
        return val.replace(":", "").upper()

    if strict:
        raise InvalidGatewayIdError(
            f"Malformed gateway ID: '{gateway_id}'. Expected bare 12-hex or colon-delimited format (e.g. '0639EA5602C1' or '06:39:EA:56:02:C1')."
        )
    return None


def filter_active_gateways(gateway_master_df: pd.DataFrame) -> pd.DataFrame:
    """Filter out decommissioned gateways from the gateway master DataFrame.
    
    Gateways with a non-null, non-empty 'decommissioned_on' date are excluded.
    Returns a copy and leaves the source DataFrame unmodified.
    """
    if "decommissioned_on" not in gateway_master_df.columns:
        return gateway_master_df.copy()

    val_series = gateway_master_df["decommissioned_on"]
    is_decommissioned = (
        val_series.notna()
        & (val_series.astype(str).str.strip() != "")
        & (val_series.astype(str).str.lower() != "nan")
        & (val_series.astype(str).str.lower() != "nat")
    )
    return gateway_master_df[~is_decommissioned].copy()


def read_csv_resilient(
    filepath_or_buffer: Union[str, pathlib.Path, io.IOBase],
    required_columns: Optional[List[str]] = None,
    dataset_name: str = "CSV file",
    **kwargs: Any,
) -> pd.DataFrame:
    """Read a CSV file trying UTF-8 first and falling back to Latin-1.
    
    Handles German character encodings (e.g. umlauts, eszett) and validates schema.
    """
    if isinstance(filepath_or_buffer, (str, pathlib.Path)):
        p = pathlib.Path(filepath_or_buffer)
        if not p.exists():
            raise FileNotFoundError(f"{dataset_name} not found at expected path: {p}")

    encodings = ["utf-8", "latin1"]
    last_error: Optional[Exception] = None
    df: Optional[pd.DataFrame] = None

    for enc in encodings:
        try:
            df = pd.read_csv(filepath_or_buffer, encoding=enc, **kwargs)
            break
        except UnicodeDecodeError as err:
            last_error = err
            continue
        except Exception as err:
            raise DataValidationError(f"Failed to parse {dataset_name}: {err}") from err

    if df is None:
        raise DataValidationError(
            f"Could not read {dataset_name} with supported encodings {encodings}: {last_error}"
        )

    if required_columns:
        validate_columns(df, required_columns, dataset_name)

    return df


def validate_columns(df: pd.DataFrame, required_columns: List[str], dataset_name: str) -> None:
    """Ensure all required columns are present in the DataFrame."""
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise DataValidationError(
            f"{dataset_name} is missing required column(s): {', '.join(missing)}. "
            f"Columns present: {list(df.columns)}"
        )
