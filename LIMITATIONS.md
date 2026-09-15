# System Limitations & Future Roadmap (LIMITATIONS.md)

This document honestly outlines the current operational boundaries and performance limitations of the gateway maintenance ranking service, along with what an additional two weeks of engineering would deliver.

---

### 1. Where the System Falls Over (Current Limitations)

* **In-Memory Windowing Overhead on Large Batches:**
  While the service optimizes telemetry ingestion by only reading partitions corresponding to the requested 28-day window and projecting required columns, calculating statistics across 320 gateways on the fly requires several seconds of CPU time during cold startup. In an enterprise setting with thousands of gateways, this on-the-fly aggregation would cause request latency spikes.
* **Weekly Granularity of Meter-Read Reporting:**
  The `meter_read_success.csv` table is compiled once per week, whereas telemetry arrives hourly. Consequently, sudden intra-week failures that occur between Wednesday and Friday cannot be confirmed via billing meter drop-rates until the following week's audit arrives, forcing the system to rely purely on backhaul telemetry anomalies.
* **Single-Process WSGI Server in Development Mode:**
  The service is currently delivered using Flask's internal WSGI server. While lightweight and portable for demonstration and testing, it is not hardened for concurrent multi-tenant production traffic without an enterprise reverse proxy (e.g. Gunicorn/Nginx).
* **Heuristic Cost Weighting vs Dynamically Trained Loss Functions:**
  The `CostRiskRanker` balances the €380 wasted visit penalty against the €600 weekly unattended failure penalty using calibrated domain heuristics and meter capacity scaling. While highly effective, transparent, and explainable, it is not a continuously learned reinforcement or Bayesian decision model.

---

### 2. What Another Two Weeks Would Deliver

1. **Persistent Incremental Feature Store (DuckDB / SQLite):**
   * Precompute and materialize daily rolling moments ($\mu, \sigma$, total disconnects, offline hours) into a local embedded DuckDB instance. Incoming hourly partitions would update moving aggregates incrementally in milliseconds, eliminating repeated parquet scans.
2. **Production Containerization & CI/CD Pipeline:**
   * Harden the container setup with multi-stage Docker builds, non-root service users, and GitHub Actions automation executing linter checks (`flake8`, `black`, `mypy`) and unit tests on every pull request.
3. **Technician Feedback Loop & Automated Resolution Tracking:**
   * Integrate an endpoint to ingest completed work orders from field visits in real time. If a technician records `Antenne getauscht` (antenna replaced), the system would immediately reset that gateway's baseline and remove it from candidate pools.
4. **Geospatial Fleet Mapping & Real-Time Telemetry Streaming:**
   * While the interactive web dashboard is already fully implemented and serving weekly recommendations, modal inspections, and live ranker swapping, another two weeks would add interactive Leaflet/Mapbox GIS maps showing gateway spatial coordinates, technician drive-time routing, and WebSocket-based streaming of hourly telemetry counters.
