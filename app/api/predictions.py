"""Prediction endpoints for weekly maintenance visit recommendations."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional
from flask import Blueprint, jsonify, request, current_app
import pandas as pd

from app.ranking.interface import BaseRanker
from app.ranking.baseline import ThreeSigmaRanker
from app.ranking.cost_aware import CostRiskRanker
from app.data.loader import DataLoader
from generate_predictions import generate_predictions, SCORED_WEEKS

predictions_bp = Blueprint("predictions", __name__, url_prefix="/api")


def _get_or_load_data(monday: dt.date):
    """Retrieve preloaded data or fetch on-demand window for arbitrary Mondays."""
    loader: DataLoader = current_app.config.get("DATA_LOADER")
    if not loader:
        loader = DataLoader()

    master_df = current_app.config.get("GATEWAY_MASTER_DF")
    if master_df is None:
        master_df = loader.load_gateway_master(active_only=True)
        current_app.config["GATEWAY_MASTER_DF"] = master_df

    meter_read_df = current_app.config.get("METER_READ_DF")
    if meter_read_df is None:
        try:
            meter_read_df = loader.load_meter_read_success()
            current_app.config["METER_READ_DF"] = meter_read_df
        except Exception:
            meter_read_df = pd.DataFrame()

    field_visits_df = current_app.config.get("FIELD_VISITS_DF")
    if field_visits_df is None:
        try:
            field_visits_df = loader.load_field_visits()
            current_app.config["FIELD_VISITS_DF"] = field_visits_df
        except Exception:
            field_visits_df = pd.DataFrame()

    telemetry_df = current_app.config.get("TELEMETRY_DF")
    start_req = pd.Timestamp(monday - dt.timedelta(days=28), tz="UTC")
    end_req = pd.Timestamp(monday, tz="UTC")

    # If telemetry not loaded or does not cover the window, load on-demand
    if telemetry_df is None or telemetry_df.empty or telemetry_df["ts"].min() > start_req or telemetry_df["ts"].max() < (end_req - dt.timedelta(hours=1)):
        telemetry_df = loader.load_telemetry(
            start_date=monday - dt.timedelta(days=28),
            end_date=monday,
            columns=["offline_duration_sec", "disconnection_cnt", "reboot_cnt"],
        )

    return master_df, telemetry_df, meter_read_df, field_visits_df


@predictions_bp.route("/predictions", methods=["GET"])
def get_predictions():
    """Retrieve top-15 gateway visit recommendations for a given Monday."""
    week_param = request.args.get("week")
    if not week_param:
        return jsonify({"error": "Missing required query parameter: 'week' (YYYY-MM-DD)"}), 400

    try:
        monday = dt.date.fromisoformat(week_param)
        if monday.weekday() != 0:
            return jsonify({"error": f"Specified date {week_param} is not a Monday"}), 400
    except ValueError:
        return jsonify({"error": f"Invalid date format '{week_param}'. Use YYYY-MM-DD"}), 400

    ranker_param = request.args.get("ranker")
    if ranker_param:
        if ranker_param.lower() in ["cost", "cost_risk", "cost-risk"]:
            ranker = CostRiskRanker()
        elif ranker_param.lower() in ["baseline", "3sigma", "baseline_3sigma"]:
            ranker = ThreeSigmaRanker()
        else:
            return jsonify({"error": f"Unknown ranker '{ranker_param}'. Choose 'baseline' or 'cost_risk'"}), 400
    else:
        ranker: BaseRanker = current_app.config.get("RANKER", ThreeSigmaRanker())

    try:
        master_df, telemetry_df, meter_read_df, field_visits_df = _get_or_load_data(monday)
    except Exception as err:
        return jsonify({"error": f"Data loading failed: {err}"}), 503

    ranked_df = ranker.rank_week(
        monday=monday,
        telemetry_df=telemetry_df,
        gateway_master_df=master_df,
        top_n=15,
        meter_read_df=meter_read_df,
        field_visits_df=field_visits_df,
    )

    return jsonify({
        "week_start": monday.isoformat(),
        "ranker": ranker.name,
        "count": len(ranked_df),
        "recommendations": ranked_df.to_dict(orient="records"),
    }), 200


@predictions_bp.route("/predictions/run", methods=["POST"])
def run_predictions():
    """Trigger prediction generation across scored weeks, updating predictions.csv."""
    data = request.get_json(silent=True) or {}
    ranker_name = data.get("ranker", "baseline")
    out_file = data.get("out", "predictions.csv")

    loader: DataLoader = current_app.config.get("DATA_LOADER")
    data_dir = loader.data_dir if loader else None

    try:
        preds = generate_predictions(
            data_dir=data_dir,
            out_path=out_file,
            ranker_name=ranker_name,
        )
        return jsonify({
            "status": "success",
            "message": f"Generated {len(preds)} predictions across {preds['week_start'].nunique()} weeks.",
            "ranker": ranker_name,
            "output_file": str(out_file),
            "weeks": sorted(preds["week_start"].unique().tolist()),
        }), 200
    except Exception as err:
        return jsonify({"error": f"Prediction generation failed: {err}"}), 500
