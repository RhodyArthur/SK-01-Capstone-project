# SK-01 Capstone Project — Multi-Source HR Data Integration Pipeline

## Purpose & Business Context

GlobalTech Corp acquired AcquiredCo and now operates two separate HR systems.
This pipeline ingests employee records from both companies, cleans and standardises
them, deduplicates cross-system matches, validates data quality, and produces a
single **golden employee dataset** ready for downstream analytics and reporting.

---

## Repository Structure

```
sk-01-capstone-project/
├── main.py                         Entry point
├── requirements.txt
├── src/
│   ├── config.py                   Logger + CONFIG dict
│   ├── utils.py                    Shared helpers (format_employee_id, KNOWN_DEPARTMENTS)
│   ├── data/
│   │   ├── raw/                    Source data files (input)
│   │   └── output/                 All generated output files
│   ├── ingestion/
│   │   ├── reader.py               Source-specific file readers
│   │   └── ingest.py               Schema alignment + ingest_all_sources()
│   ├── transforms/
│   │   ├── clean.py                Cleaning & standardisation functions
│   │   └── dedup.py                Three-pass deduplication + ghost detection
│   ├── quality/
│   │   └── validate.py             DataQualityValidator + 15-check report
│   ├── reporting/
│   │   └── visualize.py            EDA report (6-chart PNG)
│   └── output/
│       └── export.py               Golden dataset + deliverable file writer
```

---

## Input Sources

| Source              | File                                   | Format             | Key Columns                                                                                                                                                                                          |
| ------------------- | -------------------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GlobalTech HRIS     | `src/data/raw/globaltech_hris.csv`     | CSV                | `employee_id` (int), `first_name`, `last_name`, `email`, `department`, `job_title`, `hire_date`, `country`, `employment_type`, `manager_id`                                                          |
| AcquiredCo HRIS     | `src/data/raw/acquiredco_api.json`     | JSON (paginated)   | `employee_identifier` (ACQ_XXXXX), `name_first`, `name_last`, `contact_email`, `assignment_department`, `assignment_role`, `assignment_location`, `assignment_hire_timestamp`, `manager_employee_id` |
| Payroll             | `src/data/raw/payroll_data.xlsx`       | Excel (ADP export) | `employee_id`, `source` (company origin), `base_salary`, `currency`, `pay_frequency`, `bonus_target_pct`, `effective_date`                                                                           |
| Benefits Enrollment | `src/data/raw/benefits_enrollment.xml` | XML (MedShield)    | `employee_id` (GT integer), `plan_type`, `coverage_level`, `enrollment_date`, `premium_employee`, `premium_employer`                                                                                 |

---

## Output Files

All outputs are written to `src/data/output/`.

| File                          | Format                | Description                                                                                                                                         |
| ----------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `golden_employees.parquet/`   | Parquet (partitioned) | Unified, deduplicated, validated employee records. Partitioned by `company_origin` (`GlobalTech` / `AcquiredCo`).                                   |
| `ghost_employees.csv`         | CSV                   | Payroll records with no matching HRIS employee. Fields: `payroll_employee_id`, `name`, `salary_usd_annual`, `ghost_flag_reason`.                    |
| `probable_matches_review.csv` | CSV                   | Near-miss pairs for HR to confirm or reject. Fields: `record_1_id`, `record_2_id`, `similarity_score`, `hire_date_diff_days`, `recommended_action`. |
| `quality_report.csv`          | CSV                   | Results of 15 data quality checks. Fields: `check`, `description`, `total`, `passed`, `failed`, `pass_rate`, `status`.                              |
| `quality_report.html`         | HTML                  | Colour-coded HTML version of the quality report.                                                                                                    |
| `eda_report.png`              | PNG (300 DPI)         | 6-chart EDA grid: headcount by dept/country, salary by employment type, tenure distribution, benefits enrollment rate, quality summary.             |

### Golden Dataset Schema

| Column            | Type     | Description                                      | Example                           |
| ----------------- | -------- | ------------------------------------------------ | --------------------------------- |
| `employee_id`     | str      | Namespaced unique identifier                     | `GT-001234`                       |
| `first_name`      | str      | Given name (Unicode-normalised, title-cased)     | `John`                            |
| `last_name`       | str      | Family name (Unicode-normalised, title-cased)    | `Smith`                           |
| `email`           | str      | Primary work email address                       | `j.smith@globaltech.com`          |
| `department`      | str      | Department (validated against 18-value taxonomy) | `Engineering`                     |
| `job_title`       | str      | Job title as recorded in source                  | `Senior Engineer`                 |
| `hire_date`       | datetime | Date of hire (UTC midnight)                      | `2019-03-15`                      |
| `country`         | str      | Country of employment                            | `USA`                             |
| `employment_type` | str      | Employment category                              | `Full-Time`                       |
| `manager_id`      | str      | Namespaced manager ID                            | `GT-000892`                       |
| `source`          | str      | Pipeline source tag of the keeper record         | `globaltech_hris`                 |
| `company_origin`  | str      | Company of origin (partition key)                | `GlobalTech`                      |
| `employee_name`   | str      | Full name (first + last)                         | `John Smith`                      |
| `source_systems`  | str      | All contributing HRIS sources (comma-delimited)  | `globaltech_hris,acquiredco_hris` |
| `dedup_method`    | str      | Dedup pass that produced this record             | `exact_email`                     |

---

## How to Run

### Prerequisites

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Run the pipeline

```bash
python main.py
```

Logs are written to both the console (stderr) and `pipeline.log`.

### Expected run time

~35–45 seconds on a modern laptop (fuzzy deduplication is the bottleneck).

---

## Pipeline Steps

| Step              | Module                   | Description                                                                             |
| ----------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| 1 — Ingestion     | `ingestion/ingest.py`    | Reads all four sources; aligns HRIS frames to canonical schema                          |
| 2 — Cleaning      | `transforms/clean.py`    | Namespaces IDs, normalises names/dates, validates departments, converts salaries to USD |
| 3 — Deduplication | `transforms/dedup.py`    | Three-pass dedup (exact ID → exact email → fuzzy name+date); detects ghost employees    |
| 4 — Validation    | `quality/validate.py`    | 15 quality checks via `DataQualityValidator`; raises on > 2 failures                    |
| 5 — EDA Report    | `reporting/visualize.py` | Generates 6-chart 300 DPI PNG                                                           |
| 6 — Export        | `output/export.py`       | Writes golden Parquet, ghost report, and review file                                    |

---

## Known Limitations & Assumptions

- **Benefits source is GlobalTech-only.** All IDs in `benefits_enrollment.xml` are plain integers mapping to GlobalTech employees. AcquiredCo benefits enrollment data is not available in this dataset.
- **Payroll carries no employee names.** Ghost employee records therefore show `name = "N/A (payroll-only record)"`.
- **Fuzzy dedup is heuristic.** The threshold (score ≥ 88 + hire date within 30 days) was tuned on this dataset. A different name transliteration convention could cause false negatives.
- **Exchange rates are static.** USD conversion rates (EUR 1.08, GBP 1.27) are hardcoded in `clean.py` and should be updated for production use.
- **No incremental loading.** The pipeline is full-refresh; rerunning overwrites all output files.
- **AcquiredCo "ghost" IDs.** A high ghost rate (≈45% of payroll) is expected because the payroll file covers both companies but only GlobalTech IDs can be matched to benefits.

---

## Change Log

| Date       | Change                                                                                                                   |
| ---------- | ------------------------------------------------------------------------------------------------------------------------ |
| 2026-06-03 | Step 1 — Ingestion: CSV, JSON (paginated), XML, Excel readers                                                            |
| 2026-06-03 | Step 2 — Cleaning: ID namespacing, name normalisation, date parsing, currency conversion, payroll/benefits ID formatting |
| 2026-06-03 | Step 3 — Deduplication: three-pass dedup, ghost detection, provenance annotation                                         |
| 2026-06-03 | Step 4 — Validation: `DataQualityValidator` class, 15-check quality report (HTML + CSV)                                  |
| 2026-06-03 | Step 5 — EDA: 6-chart Okabe-Ito palette report at 300 DPI                                                                |
| 2026-06-03 | Step 6 — Export: golden Parquet (partitioned), ghost report CSV, review file CSV                                         |
