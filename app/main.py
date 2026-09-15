"""Main application factory and entry point."""

from __future__ import annotations

import argparse
import os
import pathlib
from typing import Optional
from flask import Flask

from app.data.loader import DataLoader, DEFAULT_DATA_DIR
from app.ranking.interface import BaseRanker
from app.ranking.baseline import ThreeSigmaRanker
from app.api.health import health_bp
from app.api.predictions import predictions_bp
from app.api.gateways import gateways_bp


def create_app(
    data_dir: Optional[pathlib.Path | str] = None,
    ranker: Optional[BaseRanker] = None,
    load_data: bool = False,
) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # 1. Configure DataLoader with default or overridden path
    loader = DataLoader(data_dir=data_dir)
    app.config["DATA_LOADER"] = loader
    app.config["DATA_DIR"] = loader.data_dir

    # 2. Configure pluggable ranker (defaults to baseline 3-sigma)
    app.config["RANKER"] = ranker if ranker is not None else ThreeSigmaRanker()

    # 3. Optional initial data loading (useful for testing or server startup)
    if load_data:
        try:
            app.config["GATEWAY_MASTER_DF"] = loader.load_gateway_master()
            # Telemetry loading will use parquet when pyarrow is installed or sample
            app.config["TELEMETRY_DF"] = loader.load_telemetry(
                columns=["gateway_id", "ts_utc", "offline_duration_sec", "disconnection_cnt", "reboot_cnt"]
            )
        except Exception as e:
            app.logger.warning(f"Initial data loading deferred: {e}")

    # 4. Register API Blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(predictions_bp)
    app.register_blueprint(gateways_bp)

    return app


def main():
    parser = argparse.ArgumentParser(description="LPDG Gateway Maintenance Ranking API")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=DEFAULT_DATA_DIR,
        help="Path to data directory (default: 03-challenge-data/data)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()

    app = create_app(data_dir=args.data, load_data=True)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
