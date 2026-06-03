"""
Three-pass deduplication for the combined HRIS frame:

  Pass 1 – exact employee_id   : removes within-source data-entry duplicates
  Pass 2 – exact email         : cross-system merge, high confidence
  Pass 3 – fuzzy name + date   : cross-system merge, medium confidence
                                  (rapidfuzz token_sort_ratio ≥ 88,
                                   hire dates within ±30 days)

Side outputs written to output/:
  probable_matches_review.csv  – near-misses for human review
  ghost_employees.csv          – payroll records with no HRIS match
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from rapidfuzz import fuzz, process

from config import CONFIG, logger
from utils import format_employee_id

# ---------------------------------------------------------------------------
# Module-level thresholds (single source of truth)
# ---------------------------------------------------------------------------
_FUZZY_THRESHOLD = 88   # minimum token_sort_ratio score to confirm a match
_DATE_WINDOW_DAYS = 30  # hire dates may differ by up to this many days


# ---------------------------------------------------------------------------
# Pass 1 – exact employee_id
# ---------------------------------------------------------------------------

def _exact_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with a duplicate employee_id (within-source data errors).

    Keeps the first occurrence; every later row sharing the same ID is
    removed.  Returns the deduplicated frame.
    """
    initial_count = len(df)
    df = df.drop_duplicates(subset=["employee_id"], keep="first")
    removed = initial_count - len(df)
    if removed:
        logger.info(f"  Pass 1 (exact ID): removed {removed} duplicate employee_id rows")
    else:
        logger.info("  Pass 1 (exact ID): no duplicate employee_ids found")
    return df


# ---------------------------------------------------------------------------
# Pass 2 – exact email
# ---------------------------------------------------------------------------

def _email_dedup(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Identify cross-system matches by normalised e-mail address.

    For every group of rows sharing the same e-mail, keep the record from
    the highest-priority source (lowest ``source_priority`` value in CONFIG)
    and discard the rest.

    Returns the deduplicated frame and a list of match-metadata dicts
    (one dict per discarded row), used later for provenance annotation.
    """
    df = df.copy()
    df["_email_norm"] = df["email"].str.lower().str.strip()

    # find all rows that share an email with at least one other row
    dupes_mask = (
        df.duplicated(subset=["_email_norm"], keep=False)
        & df["_email_norm"].notna()
    )
    email_dupes = df[dupes_mask]

    match_records: list[dict] = []
    drop_indices: list = []

    for _, group in email_dupes.groupby("_email_norm", sort=False):
        if len(group) < 2:
            continue

        # When two records match, keep the one from the higher-priority
        # source. Priority is defined in config.py (GlobalTech = 1, AcquiredCo = 2).
        group = group.copy()
        group["_priority"] = group["source"].map(CONFIG["source_priority"]).fillna(99)
        group = group.sort_values("_priority")

        keeper = group.iloc[0]
        for _, dropped_row in group.iloc[1:].iterrows():
            match_records.append({
                "keeper_id":      keeper["employee_id"],
                "keeper_source":  keeper["source"],
                "dropped_id":     dropped_row["employee_id"],
                "dropped_source": dropped_row["source"],
                "match_method":   "exact_email",
                "match_score":    100,
            })
            drop_indices.append(dropped_row.name)

    df = df.drop(index=drop_indices).drop(columns=["_email_norm"])
    logger.info(f"  Pass 2 (exact email): merged {len(match_records)} cross-system email matches")
    return df, match_records


# ---------------------------------------------------------------------------
# Pass 3 – fuzzy name + hire-date proximity
# ---------------------------------------------------------------------------

def _fuzzy_dedup(
    df: pd.DataFrame,
    threshold: int = _FUZZY_THRESHOLD,
    date_window: int = _DATE_WINDOW_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Match AcquiredCo records against GlobalTech records via fuzzy names
    and hire-date proximity.

    Strategy
    --------
    1. Block by the first letter of ``last_name`` to limit comparisons.
       (15 k GT × 3.2 k AC = 48 M raw pairs → ~1.8 M after blocking.)
    2. Within each block, use ``rapidfuzz.process.extract`` with a low
       pre-filter cutoff (75) to cheaply retrieve name candidates.
    3. For each candidate check hire-date proximity.
       • score ≥ threshold AND date within window  → confirmed match
       • score ≥ 75 but not confirmed              → near-miss (review file)

    Confirmed AC rows are dropped; their GT keeper is retained.

    Returns
    -------
    deduped_df    : frame with matched AC rows removed
    review_df     : near-miss rows for human review
    match_records : metadata for provenance annotation
    """
    df = df.copy()
    gt = df[df["source"] == "globaltech_hris"].copy()
    ac = df[df["source"] == "acquiredco_hris"].copy()

    gt["_block"] = gt["last_name"].str[0].str.upper().fillna("?")
    ac["_block"] = ac["last_name"].str[0].str.upper().fillna("?")

    match_records: list[dict] = []
    review_rows:   list[dict] = []
    drop_indices:  list       = []

    total_blocks = ac["_block"].nunique()
    logger.info(
        f"  Pass 3 (fuzzy name+date): comparing {len(ac):,} AC records "
        f"against {len(gt):,} GT records across {total_blocks} name blocks ..."
    )

    for block_key, ac_block in ac.groupby("_block"):
        gt_block = gt[gt["_block"] == block_key]
        if gt_block.empty:
            continue

        # Build {row_index: employee_name} dict for rapidfuzz lookup
        gt_names: dict = {
            idx: row["employee_name"]
            for idx, row in gt_block.iterrows()
            if pd.notna(row.get("employee_name"))
        }
        if not gt_names:
            continue

        for ac_idx, ac_row in ac_block.iterrows():
            ac_name = ac_row.get("employee_name")
            if not ac_name or pd.isna(ac_name):
                continue

            ac_date = ac_row["hire_date"]

            # rapidfuzz returns (value, score, key) sorted by score descending
            candidates = process.extract(
                ac_name,
                gt_names,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=75,    # pre-filter; anything below goes unseen
                limit=5,
            )

            confirmed = False
            best_near_miss = None   # dict or None

            for gt_name, score, gt_idx in candidates:
                gt_row  = gt_block.loc[gt_idx]
                gt_date = gt_row["hire_date"]

                # both conditions must be true to call it a confirmed match
                date_ok = (
                    pd.notna(ac_date)
                    and pd.notna(gt_date)
                    and abs((ac_date - gt_date).days) <= date_window
                )

                if score >= threshold and date_ok:
                    match_records.append({
                        "keeper_id":      gt_row["employee_id"],
                        "keeper_source":  gt_row["source"],
                        "dropped_id":     ac_row["employee_id"],
                        "dropped_source": ac_row["source"],
                        "match_method":   "fuzzy_name_date",
                        "match_score":    score,
                    })
                    drop_indices.append(ac_idx)
                    confirmed = True
                    break

                # if the name scored above 75 but didn't meet both conditions,
                # save it as a near-miss so a human can make the final call
                if best_near_miss is None:
                    date_diff = (
                        abs((ac_date - gt_date).days)
                        if pd.notna(ac_date) and pd.notna(gt_date)
                        else None
                    )
                    best_near_miss = {
                        "gt_employee_id": gt_row["employee_id"],
                        "gt_name":        gt_name,
                        "gt_hire_date":   gt_date,
                        "ac_employee_id": ac_row["employee_id"],
                        "ac_name":        ac_name,
                        "ac_hire_date":   ac_date,
                        "name_score":     score,
                        "date_diff_days": date_diff,
                    }

            if not confirmed and best_near_miss is not None:
                review_rows.append(best_near_miss)

    deduped = df.drop(index=drop_indices)
    review_df = pd.DataFrame(review_rows)

    logger.info(
        f"  Pass 3 (fuzzy name+date, threshold={threshold}, "
        f"±{date_window}d): merged {len(match_records)} matches, "
        f"{len(review_df)} near-misses queued for review"
    )
    return deduped, review_df, match_records


# ---------------------------------------------------------------------------
# Ghost employee detection
# ---------------------------------------------------------------------------

def _find_ghost_employees(
    deduped_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
) -> pd.DataFrame:
    """Return payroll rows with no matching employee in the golden HRIS frame.

    Payroll IDs are namespaced before the lookup so they align with the
    GT-XXXXXX / AC-XXXXXX format used in the deduplicated HRIS frame.

    Ghost employees may be terminated staff, contractors not tracked in HRIS,
    or data-entry errors — all warrant manual investigation.
    """
    payroll = payroll_df.copy()
    payroll["_id_ns"] = payroll.apply(
        lambda r: format_employee_id(r["employee_id"], r.get("company_origin", "")),
        axis=1,
    )

    hris_ids = set(deduped_df["employee_id"].dropna())
    ghost_mask = ~payroll["_id_ns"].isin(hris_ids)
    ghost_df = payroll_df[ghost_mask].copy()

    pct = ghost_mask.sum() / max(len(payroll), 1)
    logger.info(
        f"  Ghost employees: {len(ghost_df):,} payroll records with no HRIS match "
        f"({pct:.1%} of payroll)"
    )
    return ghost_df


# ---------------------------------------------------------------------------
# Provenance annotation
# ---------------------------------------------------------------------------

def _annotate_source_systems(
    deduped_df: pd.DataFrame,
    all_match_records: list[dict],
) -> pd.DataFrame:
    """Add ``source_systems`` and ``dedup_method`` provenance columns.

    ``source_systems``
        Comma-delimited string of every contributing source tag, e.g.
        ``"globaltech_hris,acquiredco_hris"``.  Records with no duplicate
        show only their own source.

    ``dedup_method``
        Which pass produced the merge (``"exact_email"``,
        ``"fuzzy_name_date"``), or ``"unique"`` for unmatched records.
    """
    deduped_df = deduped_df.copy()
    deduped_df["source_systems"] = deduped_df["source"]
    deduped_df["dedup_method"] = "unique"

    for match in all_match_records:
        mask = deduped_df["employee_id"] == match["keeper_id"]
        if not mask.any():
            continue
        existing = deduped_df.loc[mask, "source_systems"].values[0]
        dropped_src = match["dropped_source"]
        # split on the delimiter for exact element membership, not substring check
        if dropped_src not in existing.split(","):
            deduped_df.loc[mask, "source_systems"] = existing + "," + dropped_src
        deduped_df.loc[mask, "dedup_method"] = match["match_method"]

    return deduped_df


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def deduplicate(
    hris_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Full deduplication pipeline for the combined HRIS frame.

    Runs three passes in order (exact ID → exact email → fuzzy name+date),
    annotates provenance, detects ghost employees, and writes side outputs.

    Parameters
    ----------
    hris_df :
        Cleaned, combined HRIS frame from ``clean_hris()``.
    payroll_df :
        Cleaned payroll frame from ``normalize_currency()``.

    Returns
    -------
    deduped_df :
        Golden HRIS records – one row per real employee.
    review_df :
        Near-matches for human review
        (written to ``output/probable_matches_review.csv``).
    ghost_df :
        Payroll records with no HRIS match
        (written to ``output/ghost_employees.csv``).
    """
    logger.info("=" * 60)
    logger.info("STEP 3: Deduplication")
    logger.info(f"  Input: {len(hris_df):,} HRIS records")

    all_match_records: list[dict] = []

    df = _exact_dedup(hris_df)

    df, email_matches = _email_dedup(df)
    all_match_records.extend(email_matches)

    df, review_df, fuzzy_matches = _fuzzy_dedup(df)
    all_match_records.extend(fuzzy_matches)

    # Annotate surviving records with provenance columns
    deduped_df = _annotate_source_systems(df, all_match_records)

    removed = len(hris_df) - len(deduped_df)
    logger.info(
        f"  Deduplication complete: {len(deduped_df):,} golden records "
        f"({removed:,} duplicates removed across all passes)"
    )

    ghost_df = _find_ghost_employees(deduped_df, payroll_df)

    logger.info("STEP 3 complete.")
    return deduped_df, review_df, ghost_df
