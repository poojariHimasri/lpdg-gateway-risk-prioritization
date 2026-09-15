# Architectural & Engineering Decisions (DECISIONS.md)

**Part 2 area selected: Software Development**

This document records the five major engineering choices made during the development of the LPDG Gateway Maintenance Ranking System. For each decision, we document the choice made, the alternative approaches evaluated, and the rationale for the final selection.

---

### Decision 1: Track Selection — Part 2: Software Development
* **Choice:** Selected **Area B — Software Development**, prioritizing clean architectural separation of concerns, swappable ranking strategies via abstract contracts (`BaseRanker`), full test coverage (34 tests), rich REST API endpoints (`/predictions`, `/predictions/run`, `/gateways/<id>`, `/gateways/<id>/explain`, `/health`), robust error handling, and complete documentation.
* **Alternatives Considered:** Part 2 Track E (Machine Learning) or Track C (DevOps).
* **Why Rejected:** A complex machine learning model in production provides zero value if embedded in brittle, monolithic scripts that cannot be inspected, swapped, or operated under live scrutiny. The brief emphasizes that *"someone should be able to swap out how the ranking works without touching the API"* and that live changes will be evaluated. Building a hardened, modular software service allows any future machine learning model, statistical heuristic, or rule engine to be deployed as a drop-in replacement with zero modifications to API or operations workflows.

---

### Decision 2: Identifier Standardization to Uppercase Bare 12-Hex (`0639EA5602C1`)
* **Choice:** All gateway identifiers are normalized at ingestion to uppercase bare 12-character hexadecimal format across all modules and datasets, while external APIs permissively accept both bare and colon-delimited formats.
* **Alternatives Considered:** Preserving heterogeneous raw string formats across datasets or converting everything to colon-delimited MAC format (`06:39:EA:56:02:C1`).
* **Why Rejected:** The challenge datasets have inconsistent ID representations: `telemetry` and `meter_read_success.csv` use bare 12-hex strings, whereas `gateway_master.csv`, `field_visits.csv`, and `engineer_review_2026-02.xlsx` use colon-separated notation. Attempting inner joins without normalization resulted in silent join drops and missing statistics. Normalizing at the loader boundary guarantees reliable relational integrity across all tables while remaining fully compatible with external client calls.

---

### Decision 3: Proactive Exclusion of Decommissioned Gateways
* **Choice:** Filter out all gateways with non-null `decommissioned_on` dates in `gateway_master.csv` before ranking and prediction generation.
* **Alternatives Considered:** Allowing ranking algorithms to score all gateways present in historical telemetry, as done by the supplied `baseline_3sigma.py`.
* **Why Rejected:** During Phase 1 and baseline analysis, we discovered a critical bug in `baseline_3sigma.py`: gateway `02EBC6CD4398` was decommissioned on `2025-11-20`, yet because its past telemetry exhibited severe offline statistics, the baseline script ranked it #8 for the week of `2026-02-02`. Dispatching a technician to a retired site incurs an immediate wasted cost of **€380**. Enforcing active-only site filtering completely eliminates this failure mode.

---

### Decision 4: Pluggable Strategy Pattern for Ranking (`BaseRanker`)
* **Choice:** Decoupled ranking algorithms behind an abstract base class (`BaseRanker`), injecting the concrete implementation (`ThreeSigmaRanker` or `CostRiskRanker`) via application configuration or query parameter.
* **Alternatives Considered:** Hardcoding the 3-sigma anomaly ranking directly into the Flask API controllers or maintaining standalone execution scripts.
* **Why Rejected:** Hardcoding ranking logic tightly couples the HTTP transport layer to statistical heuristics. Under the Strategy Pattern, new ranking algorithms (such as cost-aware optimization or ML classifiers) can be tested side-by-side. The API supports dynamic parameterization (`?ranker=baseline` vs `?ranker=cost_risk`), directly fulfilling the live demonstration requirement where evaluators may ask to observe alternative ranking strategies in real time.

---

### Decision 5: Resilient Encoding Ingestion (UTF-8 with Latin-1 Fallback)
* **Choice:** Implemented automated character encoding detection with fallback from `utf-8` to `latin1` / `cp1252` when parsing CSV datasets.
* **Alternatives Considered:** Assuming universal UTF-8 encoding or manually modifying source CSV files.
* **Why Rejected:** The challenge brief expressly stated: *"The network is run with German-built software... This data will give you trouble."* In `gateway_master.csv`, German site types such as `Außenmast` contain the byte `0xDF` (`ß`), which immediately crashes standard UTF-8 readers with `UnicodeDecodeError`. Rather than altering official source files, the data loader automatically handles German character encodings, ensuring the pipeline runs reliably on fresh, uncurated production data.
