# LPDG Gateway Maintenance Ranking Service

A modular, extensible backend service and REST API designed to prioritize weekly maintenance visits for utility IoT gateways, maximizing unread meter recovery while minimizing wasted dispatches.

Built for the **LPDG Innovation Hub Selection Challenge 2026** under the **Part 2 — Software Development** track.

---

## 1. The Problem

LPDG operates a radio mesh network consisting of approximately **320 gateways** installed across rooftops, basements, and plant rooms in Germany. Each gateway relays smart meter data for **40 to 900 meters**.

When a gateway degrades or fails:
- Meter readings stop reaching the billing system.
- Failures break silently without noisy alerts; unread meters accumulate until customers receive incorrect bills or technicians are dispatched manually.
- The operations team can dispatch at most **15 technician visits per week**.
- **Business Economics**:
  - An unnecessary visit where nothing is wrong costs **€380 (wasted)**.
  - A broken gateway left unattended costs **€600 per week** in unread bills, manual work, and customer churn.

The challenge is to identify the **15 gateways most worth visiting each week**, ranked with clear, actionable operational justifications.

---

## 2. Architecture & Design Principles

The solution follows a strict separation of concerns across decoupled modules:

```text
app/
├── __init__.py
├── main.py              # Application factory & CLI runner
├── api/                 # REST API controllers & blueprints
│   ├── __init__.py
│   ├── health.py        # Service liveness & data health checks
│   ├── predictions.py   # Top-15 weekly recommendations & batch run
│   └── gateways.py      # Gateway profile lookups & ranking explanations
├── data/                # Data ingestion, resilience & normalization
│   ├── __init__.py
│   ├── loader.py        # Configurable dataset loader & Parquet windowing
│   └── processor.py     # Gateway ID normalization & active site filtering
├── features/            # Temporal feature extraction & leakage prevention
│   ├── __init__.py
│   └── engineering.py   # Anomaly statistics, meter loss rates & exposure
└── ranking/             # Pluggable ranking strategies (Strategy Pattern)
    ├── __init__.py
    ├── interface.py     # BaseRanker abstract contract
    ├── baseline.py      # 3-Sigma anomaly baseline implementation
    └── cost_aware.py    # Business risk & economics-driven ranker
```

### Key Architectural Strengths
1. **Pluggable Ranking Strategy (`BaseRanker`)**: The API controllers depend solely on the `BaseRanker` abstraction. Ranking implementations (`ThreeSigmaRanker`, `CostRiskRanker`, or future ML models) can be swapped seamlessly via configuration or query parameters without modifying API routes.
2. **Strict Time Isolation (Zero Future Leakage)**: Every feature calculation and ranking is strictly windowed before the target Monday ($t < \text{Monday}$). No future information leaks across scored weeks.
3. **Identifier Normalization**: Gateway IDs are standardized across all tables to uppercase bare 12-character hexadecimal strings (e.g. `06:39:EA:56:02:C1` $\to$ `0639EA5602C1`), ensuring robust joins across datasets.
4. **Decommissioned Gateway Exclusion**: Gateways marked decommissioned in `gateway_master.csv` are filtered out before scoring, preventing wasted €380 dispatches to retired sites.
5. **Character Encoding Resilience**: Automatic fallback from `UTF-8` to `Latin-1` (`cp1252`) handles German special characters (e.g. `Außenmast`) without ingestion crashes.

---

## 3. Data & Feature Engineering

The service ingests five official datasets from `03-challenge-data/data`:

| Dataset | Grain | Purpose |
| :--- | :--- | :--- |
| `gateway_master.csv` | Gateway | Asset metadata, meter capacity (`n_meters_installed`), site type, and decommission status. |
| `meter_read_success.csv` | Gateway $\times$ Week | Historic weekly expected vs received meter readings. |
| `field_visits.csv` | Work Order | Past technician tickets, reasons, outcomes, and parts replaced. |
| `engineer_review_2026-02.xlsx` | Gateway | Single-day manual expert audit (`Normal` vs `Schlecht`). |
| `telemetry/` | Gateway $\times$ Hour | Partitioned hourly Parquet telemetry (57 counters/signals). |

### Feature Engineering Approach
- **Meter Loss Rate**: $\text{Loss Rate} = 1 - \frac{\text{meters\_read}}{\text{meters\_expected}}$, highlighting gateways whose meters are failing to report.
- **Meters at Risk**: $\text{Exposure} = \text{Loss Rate} \times \text{n\_meters\_installed}$, prioritizing high-capacity units (e.g. 800 meters vs 40 meters).
- **Rolling Telemetry Anomalies**: Trailing 28-day gateway mean and standard deviation for `offline_duration_sec`, `disconnection_cnt`, and `reboot_cnt`. Flagged hours identify recent degradation in the last 7 days.
- **Outage Severity**: Total sustained hours offline in the trailing 7 days.
- **Visit Cooldown**: Tracks days since last technician visit. Gateways attended within 7 days receive a cooldown dampener to avoid redundant duplicate dispatches while fixes stabilize.

---

## 4. Ranking Approaches

### A. ThreeSigmaRanker (`app/ranking/baseline.py`)
Matches the official challenge baseline:
1. Calculates per-gateway mean and standard deviation over trailing 28 days for offline duration, disconnections, and reboots.
2. Flags hours in the recent 7 days exceeding $\mu + 3\sigma$.
3. Excludes decommissioned gateways (fixing a bug in the raw baseline script that selected decommissioned units).
4. Ranks gateways by flagged-hour count, returning the top 15.

### B. CostRiskRanker (`app/ranking/cost_aware.py`)
Enhances baseline scoring with business economics:
- Computes estimated weekly outage penalty averted: $\text{Value} = P(\text{Broken}) \times \left(\frac{n_{\text{meters}}}{\bar{n}}\right) \times €600 \times \text{Cooldown}$.
- Balances false-alarm risk (€380) against unattended loss (€600/week).
- Generates transparent, human-readable operational reasons (e.g., `"Rank 1: 450 meters at risk. 18h 3-sigma anomalies (offline_duration_sec) and 24h offline in trailing 7d. Visiting averts est. €600/wk unread meter loss."`).

---

## 5. Installation & Setup

### Prerequisites
- Python 3.11+
- Git

### Quick Install
```bash
# Clone the repository
git clone <repo-url>
cd LPDG-Innovation-Challenge

# Install required dependencies
pip install -r requirements.txt
```

### Configuration
The data directory defaults to `03-challenge-data/data`. You can override it via:
- CLI argument: `--data <path>`
- Environment variable: `export LPDG_DATA_DIR=<path>`

---

## 6. How to Run

### 1. Start the REST API Service
```bash
python app/main.py --data 03-challenge-data/data --port 5000
```
The service binds to `http://127.0.0.1:5000`.

### 2. Generate Predictions (`predictions.csv`)
Run the prediction generator across all 8 official scored weeks (120 rows):
```bash
# Generate using baseline 3-sigma ranker (with decommissioned filtering fix)
python generate_predictions.py --ranker baseline --out predictions.csv

# Or generate using cost-aware risk ranker
python generate_predictions.py --ranker cost_risk --out predictions.csv
```

### 3. Validate Submission
Run the official challenge validator:
```bash
python validate_submission.py predictions.csv
```
Expected output:
```text
predictions.csv: OK
  15 ranked gateways for each of 8 weeks, 2026-02-02 to 2026-03-23
```

### 4. Run the Test Suite
Execute all 33 unit, integration, API, and end-to-end tests:
```bash
# Using unittest discovery
python -m unittest discover -s tests -v

# Or using pytest
pytest -v
```

---

## 7. REST API Reference

### Health Check
* **`GET /api/health`**
* **Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "lpdg-gateway-maintenance",
  "ranker": "baseline_3sigma",
  "data_dir": "03-challenge-data/data",
  "data_dir_exists": true
}
```

### Weekly Recommendations
* **`GET /api/predictions?week=YYYY-MM-DD[&ranker=baseline|cost_risk]`**
* **Query Parameters:**
  - `week` (required): Target Monday date (e.g. `2026-02-02`).
  - `ranker` (optional): `baseline` or `cost_risk` (defaults to active ranker).
* **Response (200 OK):**
```json
{
  "week_start": "2026-02-02",
  "ranker": "baseline_3sigma",
  "count": 15,
  "recommendations": [
    {
      "week_start": "2026-02-02",
      "rank": 1,
      "gateway_id": "0639EA5602C1",
      "score": 43.0,
      "reason": "43 hour(s) beyond 3 sigma of this gateway's own 28-day baseline in the last 7 days; first breach on offline_duration_sec"
    }
  ]
}
```

### Trigger Batch Prediction Run
* **`POST /api/predictions/run`**
* **Body:** `{"ranker": "baseline", "out": "predictions.csv"}`
* **Response (200 OK):**
```json
{
  "status": "success",
  "message": "Generated 120 predictions across 8 weeks.",
  "output_file": "predictions.csv",
  "ranker": "baseline",
  "weeks": ["2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23", "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"]
}
```

### Gateway Profile Lookup
* **`GET /api/gateways/<gateway_id>`**
* Supports bare or colon-delimited format (e.g. `0639EA5602C1` or `06:39:EA:56:02:C1`).
* **Response (200 OK):**
```json
{
  "gateway_id": "0639EA5602C1",
  "tenant": "tenant_a",
  "site_type": "Außenmast",
  "region": "Niedersachsen",
  "hw_model": "GW-2100",
  "antenna_type": "Omni 3dBi",
  "fw_version": "3.3.1",
  "n_meters_installed": 113,
  "installed_on": "2023-06-19",
  "decommissioned_on": null
}
```

### Gateway Ranking Explanation
* **`GET /api/gateways/<gateway_id>/explain?week=YYYY-MM-DD`**
* Returns detailed diagnostic justification for why a specific gateway received its rank.

---

## 8. Optional Docker / DevOps

To run in a containerized environment with one command:
```bash
# Build and run with Docker Compose
docker compose up --build
```
The container mounts host data from `./03-challenge-data/data` into `/workspace/data:ro`, runs automated health checks, and starts the API service on port 5000.

---

## 9. Known Limitations

1. **Telemetry Memory Footprint**: Loading full 8-month raw Parquet partitions (~1.43 million rows) into memory requires ~0.6 GB RAM. The service mitigates this by dynamically projecting columns and slicing only the required 28-day window per target week.
2. **Meter Read Reporting Lag**: `meter_read_success.csv` is compiled weekly; telemetry is hourly. Real-time drops must rely on backhaul and radio signals until weekly meter audits arrive.
3. **Synthetic Dataset Specifics**: The challenge dataset simulates realistic utility telemetry. Real-world deployments would require adapting to vendor-specific cellular protocols and firmware schemas.
