import pandas as pd
from pathlib import Path
from config import logger
import json
import xml.etree.ElementTree as ET

_EXPECTED_CSV_COLUMNS = {
    "employee_id", "first_name", "last_name", "email",
    "department", "job_title", "hire_date", "country",
    "employment_type", "manager_id",
}

_EMPLOYMENT_TYPE_MAP = {
    "FT": "Full-Time",
    "PT": "Part-Time",
    "CONTRACTOR": "Contractor",
}

_EXPECTED_PAYROLL_COLUMNS = {
    "employee_id", "source", "base_salary", "currency",
    "pay_frequency", "bonus_target_pct", "effective_date",
}

_EXPECTED_XML_TAGS = {
    "employee_id", "plan_type", "coverage_level",
    "enrollment_date", "premium_employee", "premium_employer",
}

_PAGE_SIZE = 100


def ingest_globaltechhris_csv(filepath: Path) -> pd.DataFrame:
    """Ingest GlobalTech HRIS employee data from a UTF-8 CSV export.

    Parameters
    ----------
    filepath : Path
        Absolute path to the globaltech_hris.csv file.

    Returns
    -------
    pd.DataFrame
        Raw employee records with an added ``source`` column.
        Returns an empty DataFrame if the file is missing or unreadable.
    """
    logger.info(f"Ingesting GlobalTech HRIS CSV: {filepath}")
    try:
        df = pd.read_csv(filepath, encoding="utf-8")
    except FileNotFoundError:
        logger.error(f"[DEAD LETTER] GlobalTech HRIS file not found: {filepath}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"[DEAD LETTER] Failed to read GlobalTech HRIS CSV: {e}")
        return pd.DataFrame()

    missing_cols = _EXPECTED_CSV_COLUMNS - set(df.columns)
    if missing_cols:
        logger.warning(f"GlobalTech HRIS CSV is missing expected columns: {missing_cols}")

    df["employee_name"] = df["first_name"] + " " + df["last_name"]
    df["source"] = "globaltech_hris"
    logger.info(f"  Ingested {len(df)} records from GlobalTech HRIS CSV")
    return df


def ingest_acquiredco_json(filepath: Path, page_size: int = _PAGE_SIZE) -> pd.DataFrame:
    """Ingest AcquiredCo employee data from a BambooHR API JSON export.

    Simulates paginated API consumption by slicing the full employee list
    into pages of ``page_size`` records and processing each page in turn,
    mirroring how a real paginated REST API would be consumed.

    Parameters
    ----------
    filepath : Path
        Absolute path to the acquiredco_api.json file.
    page_size : int, optional
        Number of records per simulated page. Defaults to 100.

    Returns
    -------
    pd.DataFrame
        Flattened employee records with normalised employment type values
        and an added ``source`` column.
        Returns an empty DataFrame if the file is missing or malformed.
    """
    logger.info(f"Ingesting AcquiredCo JSON: {filepath}")
    try:
        raw = json.loads(filepath.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error(f"[DEAD LETTER] AcquiredCo JSON file not found: {filepath}")
        return pd.DataFrame()
    except json.JSONDecodeError as e:
        logger.error(f"[DEAD LETTER] Failed to decode AcquiredCo JSON: {e}")
        return pd.DataFrame()

    employees = raw.get("employees", [])
    total = len(employees)
    logger.info(f"  Total records in file: {total}")

    pages = []
    for page_num, offset in enumerate(range(0, total, page_size), start=1):
        page_records = employees[offset : offset + page_size]
        page_df = pd.json_normalize(page_records, sep="_")
        pages.append(page_df)
        logger.info(
            f"  Page {page_num}: ingested {len(page_df)} records (offset {offset}–{offset + len(page_df) - 1})"
        )

    if not pages:
        logger.warning("[DEAD LETTER] AcquiredCo JSON contained no employee records.")
        return pd.DataFrame()

    df = pd.concat(pages, ignore_index=True)

    # Normalise shortcode employment types to canonical values used across the pipeline
    df["employment_type"] = df["employment_type"].map(_EMPLOYMENT_TYPE_MAP)
    unmapped = df["employment_type"].isna().sum()
    if unmapped:
        logger.warning(f"  {unmapped} AcquiredCo records had unrecognised employment type codes.")

    df["source"] = "acquiredco_hris"
    logger.info(f"  Ingested {len(df)} total records from AcquiredCo JSON")
    return df


def ingest_payroll_excel(filepath: Path) -> pd.DataFrame:
    """Ingest combined payroll data from an ADP Excel export.

    The Excel ``source`` column identifies company origin (GlobalTech /
    AcquiredCo) and is renamed to ``company_origin`` on load to avoid
    collision with the pipeline-level ``source`` tag added here.

    Parameters
    ----------
    filepath : Path
        Absolute path to the payroll_data.xlsx file.

    Returns
    -------
    pd.DataFrame
        Payroll records with a ``source`` pipeline tag and ``company_origin``
        column.  Returns an empty DataFrame if the file is missing or
        unreadable.
    """
    logger.info(f"Ingesting payroll Excel: {filepath}")
    try:
        df = pd.read_excel(filepath, engine="openpyxl")
    except FileNotFoundError:
        logger.error(f"[DEAD LETTER] Payroll file not found: {filepath}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"[DEAD LETTER] Failed to read payroll Excel: {e}")
        return pd.DataFrame()

    missing_cols = _EXPECTED_PAYROLL_COLUMNS - set(df.columns)
    if missing_cols:
        logger.warning(f"Payroll Excel is missing expected columns: {missing_cols}")

    # Rename the Excel's 'source' (company origin) so it doesn't clash with
    # the pipeline-level 'source' tag added below.
    df = df.rename(columns={"source": "company_origin"})
    df["source"] = "payroll"
    logger.info(f"  Ingested {len(df)} records from payroll Excel")
    logger.info(f"  Unique company origins: {df['company_origin'].value_counts().to_dict()}")
    return df


def ingest_benefits_xml(filepath: Path) -> pd.DataFrame:
    """Ingest benefits enrollment data from a MedShield XML export.

    Each ``<enrollment>`` element is extracted into a flat row.  Because
    this source carries no name or email fields, the resulting DataFrame
    is intended to be joined onto the GlobalTech HRIS frame on ``employee_id``
    during the merge phase — not used as standalone employee records.

    Parameters
    ----------
    filepath : Path
        Absolute path to the benefits_enrollment.xml file.

    Returns
    -------
    pd.DataFrame
        One row per enrollment record with a ``source`` pipeline tag.
        Returns an empty DataFrame if the file is missing or malformed.
    """
    logger.info(f"Ingesting benefits XML: {filepath}")
    try:
        tree = ET.parse(filepath)
    except FileNotFoundError:
        logger.error(f"[DEAD LETTER] Benefits XML file not found: {filepath}")
        return pd.DataFrame()
    except ET.ParseError as e:
        logger.error(f"[DEAD LETTER] Failed to parse benefits XML: {e}")
        return pd.DataFrame()

    root = tree.getroot()
    records = []
    dead_letters = 0

    for enrollment in root.findall("enrollment"):
        row = {child.tag: child.text for child in enrollment}
        missing_tags = _EXPECTED_XML_TAGS - set(row.keys())
        if missing_tags:
            logger.warning(f"[DEAD LETTER] Enrollment record missing tags {missing_tags} — skipped")
            dead_letters += 1
            continue
        records.append(row)

    if dead_letters:
        logger.warning(f"  Skipped {dead_letters} malformed enrollment records")

    if not records:
        logger.warning("[DEAD LETTER] Benefits XML contained no valid enrollment records.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["source"] = "benefits"

    logger.info(f"  Ingested {len(df)} enrollment records from benefits XML")
    logger.info(f"  Unique enrolled employee IDs: {df['employee_id'].nunique()}")
    return df