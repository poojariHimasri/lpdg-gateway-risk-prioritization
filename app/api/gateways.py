"""Gateway lookup and diagnostic explanation endpoints."""

from __future__ import annotations

import datetime as dt
import pandas as pd
from flask import Blueprint, jsonify, request, current_app

from app.data.processor import normalize_gateway_id
from app.ranking.interface import BaseRanker
from app.ranking.baseline import ThreeSigmaRanker
from app.api.predictions import _get_or_load_data

gateways_bp = Blueprint("gateways", __name__, url_prefix="/api")


@gateways_bp.route("/gateways/<gateway_id>", methods=["GET"])
def get_gateway(gateway_id: str):
    """Fetch gateway profile and registration status from asset registry."""
    norm_id = normalize_gateway_id(gateway_id)
    if not norm_id:
        return jsonify({"error": f"Invalid gateway ID format: '{gateway_id}'"}), 400

    master_df = current_app.config.get("GATEWAY_MASTER_DF")
    if master_df is None:
        loader = current_app.config.get("DATA_LOADER")
        if loader:
            master_df = loader.load_gateway_master(active_only=False)
            current_app.config["GATEWAY_MASTER_DF"] = master_df
        else:
            return jsonify({"error": "Gateway master data is not loaded"}), 503

    match = master_df[master_df["gateway_id"] == norm_id]
    if match.empty:
        return jsonify({"error": f"Gateway '{norm_id}' not found in registry"}), 404

    record = match.iloc[0].to_dict()
    # Clean NaN / NaT values for reliable JSON serialization
    cleaned_record = {}
    for k, v in record.items():
        if v is None or pd.isna(v) or v is pd.NaT or str(v).lower() in ["nan", "nat"]:
            cleaned_record[k] = None
        elif isinstance(v, (dt.date, dt.datetime)):
            cleaned_record[k] = v.isoformat()
        else:
            cleaned_record[k] = v

    return jsonify(cleaned_record), 200


@gateways_bp.route("/gateways/<gateway_id>/explain", methods=["GET"])
def explain_gateway(gateway_id: str):
    """Explain why a particular gateway was assigned its rank for a given week."""
    norm_id = normalize_gateway_id(gateway_id)
    if not norm_id:
        return jsonify({"error": f"Invalid gateway ID format: '{gateway_id}'"}), 400

    week_param = request.args.get("week")
    if not week_param:
        return jsonify({"error": "Missing required query parameter: 'week' (YYYY-MM-DD)"}), 400

    try:
        monday = dt.date.fromisoformat(week_param)
        if monday.weekday() != 0:
            return jsonify({"error": f"Specified date {week_param} is not a Monday"}), 400
    except ValueError:
        return jsonify({"error": f"Invalid date format '{week_param}'. Use YYYY-MM-DD"}), 400

    ranker: BaseRanker = current_app.config.get("RANKER", ThreeSigmaRanker())

    try:
        master_df, telemetry_df, meter_read_df, field_visits_df = _get_or_load_data(monday)
    except Exception as err:
        return jsonify({"error": f"Data loading failed: {err}"}), 503

    # Check if gateway exists in registry
    match = master_df[master_df["gateway_id"] == norm_id]
    if match.empty:
        return jsonify({"error": f"Gateway '{norm_id}' not found in registry"}), 404

    explanation = ranker.explain_gateway(
        monday=monday,
        gateway_id=norm_id,
        telemetry_df=telemetry_df,
        gateway_master_df=master_df,
        meter_read_df=meter_read_df,
        field_visits_df=field_visits_df,
    )

    return jsonify(explanation), 200
