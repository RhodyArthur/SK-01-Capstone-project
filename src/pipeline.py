from __future__ import annotations

from datetime import datetime

from config import CONFIG, logger
from ingestion.ingest import ingest_all_sources
from transforms.clean import clean_hris, normalize_currency
from transforms.dedup import deduplicate
from quality.validate import validate


def run_pipeline() -> None:
    """Main pipeline entry point."""

    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("Multi-source HR Data Integration PIPELINE")
    logger.info(f"Run started: {start_time.isoformat()}")
    logger.info("=" * 60)

    result = ingest_all_sources()
    input_count = len(result["hris"])

    hris_clean    = clean_hris(result["hris"])
    payroll_clean = normalize_currency(result["payroll"])

    deduped, review_df, ghost_df = deduplicate(hris_clean, payroll_clean)

    quality_report = validate(deduped, ghost_df)

    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Input records:           {input_count:,}")
    logger.info(f"  Golden records:          {len(deduped):,}")
    logger.info(f"  Review candidates:       {len(review_df):,}")
    logger.info(f"  Ghost employees:         {len(ghost_df):,}")
    logger.info(f"  Quality checks passed:   {int((quality_report['status'] == 'PASS').sum())}/{len(quality_report)}")
    logger.info(f"  Duration:                {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
