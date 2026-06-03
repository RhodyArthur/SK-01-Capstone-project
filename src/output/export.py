"""
Golden Dataset & Documentation Outputs.

Writes all final deliverable files to CONFIG["output_dir"]:

  golden_employees.parquet          Unified golden HRIS records,
                                    partitioned by company_origin.
  ghost_employees.csv               Payroll records with no HRIS match,
                                    formatted to the deliverable spec.
  probable_matches_review.csv       Near-miss pairs for HR review,
                                    formatted to the deliverable spec.
"""
from __future__ import annotations

import pandas as pd

from config import CONFIG, logger


# Schema documentation for the golden Parquet dataset.
GOLDEN_SCHEMA_DOCS = [
    ("employee_id",    "str",      "Namespaced unique employee identifier",                         "GT-001234"),
    ("first_name",     "str",      "Given name, Unicode-normalised and title-cased",                "John"),
    ("last_name",      "str",      "Family name, Unicode-normalised and title-cased",               "Smith"),
    ("email",          "str",      "Primary work email address",                                    "j.smith@globaltech.com"),
    ("department",     "str",      "Department name (validated against 18-value taxonomy)",         "Engineering"),
    ("job_title",      "str",      "Job title as recorded in the source system",                    "Senior Engineer"),
    ("hire_date",      "datetime", "Date of hire (UTC midnight, NaT if unparseable)",               "2019-03-15"),
    ("country",        "str",      "Country of employment",                                         "USA"),
    ("employment_type","str",      "Employment category",                                           "Full-Time"),
    ("manager_id",     "str",      "Namespaced ID of direct manager (NaN if top-level)",            "GT-000892"),
    ("source",         "str",      "Pipeline source tag of the winning (keeper) HRIS record",      "globaltech_hris"),
    ("company_origin", "str",      "Company the employee originated from (partition key)",          "GlobalTech"),
    ("employee_name",  "str",      "Concatenated full name (first + last)",                        "John Smith"),
    ("hire_date_flag", "str",      "Date range validation result: ok | out_of_range",              "ok"),
    ("source_systems", "str",      "Comma-delimited all contributing HRIS sources for this record", "globaltech_hris,acquiredco_hris"),
    ("dedup_method",   "str",      "Dedup pass that produced this golden record",                  "exact_email"),
]


def export_golden_dataset(deduped_df: pd.DataFrame) -> None:
    """Write the golden employee records as a Parquet dataset partitioned by
    ``company_origin``.

    Pyarrow creates one subdirectory per partition value, e.g.::

        output/golden_employees.parquet/
            company_origin=GlobalTech/
                part-0.parquet
            company_origin=AcquiredCo/
                part-0.parquet

    Parameters
    ----------
    deduped_df :
        Deduplicated, validated HRIS frame from the pipeline.
    """
    output_dir = CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "golden_employees.parquet"

    # Drop internal helper columns that are not part of the deliverable schema
    drop_cols = [c for c in ("hire_date_flag",) if c in deduped_df.columns]
    export_df = deduped_df.drop(columns=drop_cols) if drop_cols else deduped_df.copy()

    # Parquet requires consistent dtypes; ensure hire_date is datetime[ns]
    if "hire_date" in export_df.columns:
        export_df["hire_date"] = pd.to_datetime(export_df["hire_date"], errors="coerce")

    export_df.to_parquet(
        parquet_path,
        partition_cols=["company_origin"],
        engine="pyarrow",
        index=False,
        existing_data_behavior="delete_matching",
    )

    partitions = export_df["company_origin"].value_counts().to_dict()
    logger.info(f"  Golden dataset written: {parquet_path}")
    for origin, count in partitions.items():
        logger.info(f"    company_origin={origin}: {count:,} records")


# ---------------------------------------------------------------------------
# Ghost employee report
# ---------------------------------------------------------------------------

def export_ghost_report(ghost_df: pd.DataFrame) -> None:
    """Write the ghost employee report with deliverable-spec columns.

    Ghost employees are payroll records that have no matching HRIS entry.
    Because the payroll source carries no employee names, the ``name`` field
    is populated as "N/A (payroll-only record)".

    Output columns
    --------------
    payroll_employee_id   Namespaced payroll employee ID (GT-/AC-)
    name                  Not available in payroll source
    salary_usd_annual     Annual salary in USD
    ghost_flag_reason     Why the record was flagged
    """
    output_dir = CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    if ghost_df.empty:
        logger.info("  Ghost report: no ghost employees — skipping file write")
        return

    report = pd.DataFrame({
        "payroll_employee_id": ghost_df["employee_id"],
        "name":                "N/A (payroll-only record)",
        "salary_usd_annual":   ghost_df.get("salary_usd_annual", pd.NA),
        "ghost_flag_reason":   "No matching HRIS employee record",
    })

    ghost_path = output_dir / "ghost_employees.csv"
    report.to_csv(ghost_path, index=False)
    logger.info(f"  Ghost report written: {ghost_path} ({len(report):,} records)")


# ---------------------------------------------------------------------------
# Probable-match review file
# ---------------------------------------------------------------------------

def _recommended_action(score: float, date_diff) -> str:
    """Derive a review recommendation from the fuzzy score and date gap."""
    if score >= 88:
        # Strong name match but hire date was too far apart to auto-confirm
        return "VERIFY_HIRE_DATE"
    return "MANUAL_REVIEW"


def export_review_file(review_df: pd.DataFrame) -> None:
    """Write the probable-match review file with deliverable-spec columns.

    Near-miss pairs are records whose names fuzzy-matched (score ≥ 75) but
    that did not meet the full confirmation criteria (score ≥ 88 AND hire
    dates within 30 days).

    Output columns
    --------------
    record_1_id          GlobalTech employee ID (the GT keeper candidate)
    record_2_id          AcquiredCo employee ID (the AC candidate)
    similarity_score     rapidfuzz token_sort_ratio name similarity (0–100)
    hire_date_diff_days  Absolute difference in hire dates (NaN if either missing)
    recommended_action   VERIFY_HIRE_DATE | MANUAL_REVIEW
    """
    output_dir = CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    if review_df.empty:
        logger.info("  Review file: no near-misses — skipping file write")
        return

    recommended = review_df.apply(
        lambda r: _recommended_action(r["name_score"], r["date_diff_days"]), axis=1
    )

    report = pd.DataFrame({
        "record_1_id":         review_df["gt_employee_id"],
        "record_2_id":         review_df["ac_employee_id"],
        "similarity_score":    review_df["name_score"].round(1),
        "hire_date_diff_days": review_df["date_diff_days"],
        "recommended_action":  recommended,
    })

    review_path = output_dir / "probable_matches_review.csv"
    report.to_csv(review_path, index=False)
    logger.info(f"  Review file written: {review_path} ({len(report):,} pairs)")
    action_counts = recommended.value_counts().to_dict()
    for action, count in action_counts.items():
        logger.info(f"    {action}: {count:,}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def export_all(
    deduped_df: pd.DataFrame,
    review_df: pd.DataFrame,
    ghost_df: pd.DataFrame,
) -> None:
    """Write all Step 6 deliverable output files."""
    logger.info("=" * 60)
    logger.info("STEP 6: Golden Dataset & Output Files")

    export_golden_dataset(deduped_df)
    export_ghost_report(ghost_df)
    export_review_file(review_df)

    logger.info("STEP 6 complete.")
