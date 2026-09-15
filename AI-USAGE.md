# AI Usage Disclosure (AI-USAGE.md)

### 1. What AI Tools Were Used For
* **Architectural Scaffolding:** Assisting in structuring the modular layout (Data Loader, Feature Engineering, Pluggable Rankers, Flask API, and Test Suites).
* **Test Suite Expansion:** Generating unit test permutations for gateway ID normalization, edge-case MAC representations, and route error handlers.
* **Pure-Python Fallback Parser:** Creating a lightweight XML-based XLSX reader using Python's standard library `zipfile` and `xml.etree.ElementTree` to inspect `engineer_review_2026-02.xlsx` before `openpyxl` was installed.
* **Documentation Drafting:** Accelerating Markdown draft generation for API endpoint schemas, docstrings, and limitation summaries.

---

### 2. Discrepancies Spotted & Corrected

#### Issue 1: UTF-8 Ingestion Assumption on German Encodings
* **The Error:** AI code generation initially used standard `pd.read_csv(path)` assuming default UTF-8 encoding across all files.
* **The Catch:** Running ingestion on `gateway_master.csv` threw `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xdf in position 161`. The byte `0xDF` is the German character `ß` (Eszett) in ISO-8859-1 (Latin-1) from site types like `Außenmast`.
* **The Fix:** Created `read_csv_resilient()` in `app/data/processor.py` with automatic fallback to Latin-1/CP1252, preserving German special characters without crashing.

#### Issue 2: Baseline Anomaly Blindness to Decommissioned Gateways
* **The Error:** Initial ranking logic followed `baseline_3sigma.py` without checking gateway retirement status.
* **The Catch:** Analysis revealed that gateway `02EBC6CD4398` was decommissioned on `2025-11-20`, yet ranked #8 in week `2026-02-02` because its past telemetry showed high offline duration. A field visit to a retired gateway incurs an immediate €380 wasted dispatch cost.
* **The Fix:** Implemented `filter_active_gateways()` to strictly exclude all decommissioned units from recommendation candidates.

#### Issue 3: Excel Serial Date Conversion in XML Parser
* **The Error:** An AI-generated XML parser extracted cell text `'46068'` for `reviewed_on` as an arbitrary string, causing `pd.to_datetime('46068')` to evaluate to `NaT`.
* **The Catch:** Inspection showed that `46068` was an unformatted Excel serial day offset from base date `1899-12-30` (representing `2026-02-15`).
* **The Fix:** Added an explicit Excel serial date conversion routine in `load_engineer_review()` to correctly evaluate serial date values into Python `datetime.date` objects.
