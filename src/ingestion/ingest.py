import pandas as pd
import numpy as np
from config import logger, CONFIG
from ingestion.reader import (
    ingest_globaltechhris_csv,
    ingest_acquiredco_json,
    ingest_benefits_xml,
    ingest_payroll_excel,
)

# Canonical employee columns shared by all HRIS sources after alignment.
STANDARD_SCHEMA = [
    "employee_id", "first_name", "last_name", "email",
    "department", "job_title", "hire_date", "country",
    "employment_type", "manager_id", "source", "company_origin",
]

# AcquiredCo columns produced by pd.json_normalize(sep="_") -> canonical names.
_ACQUIREDCO_RENAME = {
    "employee_identifier":   "employee_id",
    "name_first":            "first_name",
    "name_last":             "last_name",
    "contact_email":         "email",
    "assignment_department": "department",
    "assignment_role":       "job_title",
    "assignment_location":   "country",
    "assignment_hire_timestamp": "hire_date",
    "manager_employee_id":   "manager_id",
}

_COMPANY_ORIGIN = {
    "globaltech_hris": "GlobalTech",
    "acquiredco_hris": "AcquiredCo",
}


def align_schema(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Rename source-specific columns to the canonical schema and enforce
    STANDARD_SCHEMA column order.

    Parameters
    ----------
    df : pd.DataFrame
        Raw DataFrame returned by a reader function.
    source_name : str
        Pipeline source tag (e.g. ``"acquiredco_hris"``). Used to select
        the correct column rename map and assign ``company_origin``.

    Returns
    -------
    pd.DataFrame
        DataFrame aligned to STANDARD_SCHEMA with metadata columns retained.
    """
    if source_name == "acquiredco_hris":
        df = df.rename(columns=_ACQUIREDCO_RENAME)

    df["company_origin"] = _COMPANY_ORIGIN.get(source_name, "Unknown")

    for col in STANDARD_SCHEMA:
        if col not in df.columns:
            df[col] = np.nan

    return df[STANDARD_SCHEMA].copy()


def ingest_all_sources() -> dict[str, pd.DataFrame]:
    """Ingest all supported sources.

    HRIS sources (GlobalTech + AcquiredCo) are schema-aligned and concatenated
    into a single employee frame. Benefits and payroll are returned as separate
    DataFrames because they carry different schemas and are intended to be
    joined onto the HRIS frame during the clean/merge phase

    Returns
    -------
    dict with keys:
        ``"hris"``     -- combined, schema-aligned HRIS employee records
        ``"benefits"`` -- benefits enrollment records (join-time source)
        ``"payroll"``  -- payroll records (join-time source)
    """
    logger.info("=" * 60)
    logger.info("STEP 1: Data Ingestion")

    hris_frames = []

    globaltech_df = ingest_globaltechhris_csv(CONFIG["input_dir"] / "globaltech_hris.csv")
    if not globaltech_df.empty:
        hris_frames.append(align_schema(globaltech_df, "globaltech_hris"))

    acquiredco_df = ingest_acquiredco_json(CONFIG["input_dir"] / "acquiredco_api.json")
    if not acquiredco_df.empty:
        hris_frames.append(align_schema(acquiredco_df, "acquiredco_hris"))

    if hris_frames:
        hris_combined = pd.concat(hris_frames, ignore_index=True)
    else:
        hris_combined = pd.DataFrame(columns=STANDARD_SCHEMA)
        logger.warning("No HRIS frames loaded; combined HRIS frame is empty.")

    logger.info(f"  Combined HRIS records: {len(hris_combined)}")
    for src, grp in hris_combined.groupby("source", sort=False):
        logger.info(f"    {src}: {len(grp)} records")

    benefits_df = ingest_benefits_xml(CONFIG["input_dir"] / "benefits_enrollment.xml")
    payroll_df  = ingest_payroll_excel(CONFIG["input_dir"] / "payroll_data.xlsx")

    logger.info(f"  Benefits enrollment records: {len(benefits_df)}")
    logger.info(f"  Payroll records: {len(payroll_df)}")
    logger.info("STEP 1 complete.")

    return {
        "hris":     hris_combined,
        "benefits": benefits_df,
        "payroll":  payroll_df,
    }