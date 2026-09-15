"""Health check endpoint and service status diagnostics."""

from __future__ import annotations

from flask import Blueprint, jsonify, current_app

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint checking application state and data access."""
    loader = current_app.config.get("DATA_LOADER")
    ranker = current_app.config.get("RANKER")

    data_dir_exists = False
    if loader and hasattr(loader, "data_dir"):
        data_dir_exists = loader.data_dir.exists()

    status = "healthy" if data_dir_exists else "degraded"
    return jsonify({
        "status": status,
        "service": "lpdg-gateway-maintenance",
        "ranker": ranker.name if ranker else None,
        "data_dir_exists": data_dir_exists,
        "data_dir": str(loader.data_dir) if loader else None,
    }), (200 if status == "healthy" else 503)
