from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import CONFIG, logger
from utils import KNOWN_DEPARTMENTS

# Pipeline halts if MORE than this many checks fail.
_MAX_FAILURES = 2


class DataQualityValidator:
    """Run configurable quality checks against the golden HRIS frame.

    Each check method records a result dict and returns it.
    Call generate_report() at the end to get the full summary DataFrame
    and write it to disk.
    """

    def __init__(self, df: pd.DataFrame, threshold: float = CONFIG["quality_threshold"]):
        self.df = df
        self.threshold = threshold
        self.results: list[dict] = []
        self.n = len(df)

    def _record(self, check: str, description: str, failed: int, total: int) -> dict:
        pass_rate = 1 - (failed / total) if total > 0 else 1.0
        result = {
            "check":       check,
            "description": description,
            "total":       total,
            "passed":      total - failed,
            "failed":      failed,
            "pass_rate":   round(pass_rate, 4),
            "status":      "PASS" if pass_rate >= self.threshold else "FAIL",
        }
        self.results.append(result)
        return result

    def check_not_null(self, column: str, description: str) -> dict:
        failed = int(self.df[column].isna().sum())
        return self._record(f"NOT NULL: {column}", description, failed, self.n)

    def check_unique(self, column: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int(non_null.duplicated().sum())
        return self._record(f"UNIQUE: {column}", description, failed, len(non_null))

    def check_regex(self, column: str, pattern: str, description: str) -> dict:
        non_null = self.df[column].dropna().astype(str)
        failed = int((~non_null.str.match(pattern, na=False)).sum())
        return self._record(f"REGEX: {column}", description, failed, len(non_null))

    def check_values_in_set(self, column: str, valid_values: list, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.isin(valid_values)).sum())
        return self._record(f"VALUES IN SET: {column}", description, failed, len(non_null))

    def check_date_range(
        self, column: str, min_date: str, max_date: str, description: str
    ) -> dict:
        non_null = self.df[column].dropna()
        in_range = non_null.between(pd.Timestamp(min_date), pd.Timestamp(max_date))
        failed = int((~in_range).sum())
        return self._record(f"DATE RANGE: {column}", description, failed, len(non_null))

    def check_flag_rate(
        self, column: str, flag_value: str, max_rate: float, description: str
    ) -> dict:
        """Pass when the fraction of rows matching flag_value is <= max_rate."""
        flagged = int((self.df[column] == flag_value).sum())
        rate = flagged / self.n if self.n > 0 else 0
        # treat as "failed rows" relative to a synthetic total so _record works cleanly
        # we call it failed only if the overall rate breaches max_rate
        exceeded = rate > max_rate
        result = {
            "check":       f"FLAG RATE: {column}={flag_value}",
            "description": description,
            "total":       self.n,
            "passed":      self.n - flagged if not exceeded else 0,
            "failed":      flagged if exceeded else 0,
            "pass_rate":   round(1 - rate, 4),
            "status":      "FAIL" if exceeded else "PASS",
        }
        self.results.append(result)
        return result

    def check_column_present(self, column: str, description: str) -> dict:
        present = column in self.df.columns
        result = {
            "check":       f"COLUMN PRESENT: {column}",
            "description": description,
            "total":       1,
            "passed":      1 if present else 0,
            "failed":      0 if present else 1,
            "pass_rate":   1.0 if present else 0.0,
            "status":      "PASS" if present else "FAIL",
        }
        self.results.append(result)
        return result

    def check_min_row_count(self, min_count: int, description: str) -> dict:
        passed = self.n >= min_count
        result = {
            "check":       "MIN ROW COUNT",
            "description": description,
            "total":       self.n,
            "passed":      self.n if passed else 0,
            "failed":      0 if passed else min_count - self.n,
            "pass_rate":   1.0 if passed else round(self.n / min_count, 4),
            "status":      "PASS" if passed else "FAIL",
        }
        self.results.append(result)
        return result

    def generate_report(self) -> pd.DataFrame:
        report = pd.DataFrame(self.results)
        logger.info("=" * 60)
        logger.info("DATA QUALITY REPORT")
        logger.info("=" * 60)
        for item in self.results:
            icon = "PASS" if item["status"] == "PASS" else "FAIL"
            logger.info(
                f"  [{icon}] {item['check']}: {item['pass_rate']:.1%} "
                f"({item['failed']} failed of {item['total']})"
            )
        overall = bool((report["status"] == "PASS").all()) if not report.empty else True
        logger.info("=" * 60)
        logger.info(f"  OVERALL: {'ALL CHECKS PASSED' if overall else 'SOME CHECKS FAILED'}")
        logger.info("=" * 60)
        return report


def run_quality_checks(
    deduped_df: pd.DataFrame,
    ghost_df: pd.DataFrame,
) -> pd.DataFrame:
    """Run all HR data quality checks and write output reports.

    Parameters
    ----------
    deduped_df : golden HRIS records from deduplicate()
    ghost_df   : payroll records with no HRIS match from deduplicate()

    Returns
    -------
    pd.DataFrame  report with one row per check
    """
    today = datetime.now().strftime("%Y-%m-%d")
    threshold = CONFIG["quality_threshold"]
    validator = DataQualityValidator(deduped_df, threshold=threshold)

    validator.check_not_null("employee_id", "Every golden record must have an employee_id")
    validator.check_unique("employee_id", "employee_ids must be unique after deduplication")
    validator.check_regex(
        "employee_id", r"^(GT|AC)-\d{6}$",
        "employee_ids must follow the GT-XXXXXX or AC-XXXXXX format"
    )

    validator.check_not_null("first_name", "Every employee must have a first name")
    validator.check_not_null("last_name",  "Every employee must have a last name")

    validator.check_not_null(
        "email", "At least 90% of employees should have an email address"
    )
    validator.check_regex(
        "email", r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        "Email addresses must be in a valid format"
    )
    validator.check_unique("email", "Email addresses must be unique after deduplication")

    validator.check_not_null("hire_date", "Every employee must have a hire date")
    validator.check_date_range(
        "hire_date", "1970-01-01", today,
        "Hire dates must fall between 1970-01-01 and today"
    )

    validator.check_not_null("department", "Every employee must be assigned to a department")
    validator.check_values_in_set(
        "department", KNOWN_DEPARTMENTS,
        "All department values must match the approved taxonomy"
    )

    validator.check_column_present(
        "source_systems",
        "Dedup step must annotate each record with its contributing source systems"
    )

    validator.check_min_row_count(
        1000, "Golden dataset must contain at least 1,000 employee records"
    )

    # --- Ghost employee rate (payroll without HRIS match) ---
    # Approximated as ghosts / (ghosts + golden); flag if > 75%
    ghost_count = len(ghost_df) if ghost_df is not None else 0
    approximate_total = len(deduped_df) + ghost_count
    ghost_rate = ghost_count / approximate_total if approximate_total > 0 else 0
    ghost_result = {
        "check":       "GHOST RATE: payroll vs HRIS",
        "description": "Payroll records with no HRIS match should stay below 75%",
        "total":       approximate_total,
        "passed":      len(deduped_df) if ghost_rate < 0.75 else 0,
        "failed":      ghost_count if ghost_rate >= 0.75 else 0,
        "pass_rate":   round(1 - ghost_rate, 4),
        "status":      "FAIL" if ghost_rate >= 0.75 else "PASS",
    }
    validator.results.append(ghost_result)

    report = validator.generate_report()

    # write outputs
    output_dir = CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    report.to_csv(output_dir / "quality_report.csv", index=False)
    logger.info(f"  Report written: {output_dir / 'quality_report.csv'}")

    _write_html_report(report, output_dir / "quality_report.html")
    logger.info(f"  Report written: {output_dir / 'quality_report.html'}")

    failed_checks = report[report["status"] == "FAIL"]
    if len(failed_checks) > _MAX_FAILURES:
        raise RuntimeError(
            f"Data quality gate FAILED: {len(failed_checks)}/{len(report)} checks failed "
            f"(max allowed: {_MAX_FAILURES}). Review output/quality_report.csv for details."
        )

    return report


def validate(deduped_df: pd.DataFrame, ghost_df: pd.DataFrame) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("STEP 4: Data Quality Validation")
    report = run_quality_checks(deduped_df, ghost_df)
    logger.info("STEP 4 complete.")
    return report


def _write_html_report(report_df: pd.DataFrame, filepath: Path) -> None:
    rows_html = ""
    for _, row in report_df.iterrows():
        colour = "#d4edda" if row["status"] == "PASS" else "#f8d7da"
        rows_html += (
            f'<tr style="background:{colour}">'
            f'<td>{row["check"]}</td>'
            f'<td><b>{row["status"]}</b></td>'
            f'<td>{row["pass_rate"]:.1%}</td>'
            f'<td>{row["failed"]} / {row["total"]}</td>'
            f'<td>{row["description"]}</td>'
            f'</tr>\n'
        )

    passed = int((report_df["status"] == "PASS").sum())
    failed = int((report_df["status"] == "FAIL").sum())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>HR Pipeline — Data Quality Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2em; }}
    h1 {{ color: #333; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th {{ background: #343a40; color: white; padding: 8px 12px; text-align: left; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #dee2e6; }}
  </style>
</head>
<body>
  <h1>HR Data Integration — Quality Report</h1>
  <p>Total checks: {len(report_df)} &nbsp;|&nbsp;
     Passed: {passed} &nbsp;|&nbsp;
     Failed: {failed}</p>
  <table>
    <thead>
      <tr>
        <th>Check</th><th>Status</th><th>Pass Rate</th>
        <th>Failed / Total</th><th>Description</th>
      </tr>
    </thead>
    <tbody>
{rows_html}    </tbody>
  </table>
</body>
</html>
"""
    filepath.write_text(html, encoding="utf-8")
