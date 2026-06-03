import pandas as pd
import numpy as np
import unicodedata
from config import logger
from utils import format_employee_id, KNOWN_DEPARTMENTS

_FREQUENCY_MULTIPLIER = {"Annual": 1, "Monthly": 12, "Bi-Weekly": 26}

_EXCHANGE_RATES_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}

# employee id namespacing
def namespace_employee_ids(df: pd.DataFrame) -> pd.DataFrame:
    if 'company_origin' not in df.columns:
        logger.warning("No company origin column found")
        return df

    df['employee_id'] = df.apply(
        lambda row: format_employee_id(row['employee_id'], row['company_origin']), axis=1
    )
    df['manager_id'] = df.apply(
        lambda row: format_employee_id(row['manager_id'], row['company_origin']), axis=1
    )
    return df

# name standardization
def clean_names(df: pd.DataFrame)-> pd.DataFrame:
    def fix_name(name):
        if pd.isna(name):
            return name
        name = unicodedata.normalize('NFC', str(name)).strip()
        words = name.replace('-', ' ').replace("'", ' ').replace(',', ' ')
        return ' '.join(words.split()).title()
    df['first_name'] = df['first_name'].apply(fix_name)
    df['last_name'] = df['last_name'].apply(fix_name)
    df['employee_name'] = df['first_name'] + ' ' + df['last_name']
    return df

def standardize_dates(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize to plain YYYY-MM-DD before parsing.
    df['hire_date'] = pd.to_datetime(
        df['hire_date'].str[:10], errors='coerce', format='%Y-%m-%d'
    )
    today = pd.Timestamp.today().normalize()
    df['hire_date_flag'] = df['hire_date'].apply(
        lambda d: 'out_of_range' if pd.isna(d) or d < pd.Timestamp('1970-01-01') or d > today else 'ok'
    )
    return df

def map_departments(df: pd.DataFrame) -> pd.DataFrame:
    if 'department' not in df.columns:
        logger.warning("No department column found")
        return df

    unknown_mask = ~df['department'].isin(KNOWN_DEPARTMENTS) & df['department'].notna()
    unknown_count = int(unknown_mask.sum())

    if unknown_count:
        unknown_rows = df.loc[unknown_mask, ['employee_id', 'department']]
        for _, row in unknown_rows.iterrows():
            logger.warning(f"Unknown department '{row['department']}' for employee {row['employee_id']}")
        logger.warning(f"  Total unknown departments: {unknown_count} records flagged for manual review")
    else:
        logger.info("  All department values match known taxonomy")

    return df
        
def normalize_currency(df: pd.DataFrame) -> pd.DataFrame:
    """Convert payroll salaries to a common USD annual figure.

    Applies to the payroll DataFrame. Retains the
    original ``base_salary``, ``currency``, and ``pay_frequency`` columns
    and adds ``salary_usd_annual`` as a new column.
    """
    if df.empty:
        return df

    # --- A: clean salary string → float ---
    # base_salary from Excel is usually already numeric, but defensively
    # handle string formats like "$85,000" in case of mixed inputs.
    def parse_salary(value):
        if pd.isna(value):
            return np.nan
        try:
            return float(str(value).replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip())
        except ValueError:
            logger.warning(f"Could not parse salary value: '{value}' — set to NaN")
            return np.nan

    cleaned = df['base_salary'].apply(parse_salary)

    # --- B: map pay frequency to annual multiplier ---
    multiplier = df['pay_frequency'].map(_FREQUENCY_MULTIPLIER)
    unmapped_freq = df.loc[multiplier.isna(), 'pay_frequency'].dropna().unique().tolist()
    if unmapped_freq:
        logger.warning(f"  Unrecognised pay_frequency values (set to NaN): {unmapped_freq}")

    # --- C: map currency to USD exchange rate ---
    usd_rate = df['currency'].map(_EXCHANGE_RATES_USD)
    unmapped_curr = df.loc[usd_rate.isna(), 'currency'].dropna().unique().tolist()
    if unmapped_curr:
        logger.warning(f"  Unrecognised currency values (set to NaN): {unmapped_curr}")

    df['salary_usd_annual'] = cleaned * multiplier * usd_rate

    computed = int(df['salary_usd_annual'].notna().sum())
    logger.info(f"  salary_usd_annual computed for {computed}/{len(df)} payroll records")
    return df

def clean_hris(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all cleaning transformations to the combined HRIS DataFrame.

    Runs each cleaning step in the required order and returns the fully
    cleaned frame. ``normalize_currency`` is intentionally excluded here
    because it operates on the payroll DataFrame, not the HRIS frame.

    Parameters
    ----------
    df : pd.DataFrame
        Combined HRIS frame produced by ``ingest_all_sources``.

    Returns
    -------
    pd.DataFrame
        Cleaned HRIS frame with standardised IDs, names, dates, and
        department validation applied.
    """
    logger.info("STEP 2: Cleaning & Standardization")
    df = df.copy()

    df = namespace_employee_ids(df)
    df = clean_names(df)
    df = standardize_dates(df)
    flagged = int((df['hire_date_flag'] == 'out_of_range').sum())
    if flagged:
        logger.warning(f"      {flagged} records have out-of-range hire dates")
    else:
        logger.info("      All hire dates within plausible range")

    df = map_departments(df)

    logger.info(f"STEP 2 complete. {len(df)} records cleaned.")
    return df

    
