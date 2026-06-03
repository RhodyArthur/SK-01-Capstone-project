from __future__ import annotations

from datetime import datetime

from config import CONFIG, logger
from ingestion.ingest import ingest_all_sources
from transforms.clean import clean_hris, normalize_currency


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
    print(hris_clean[hris_clean['hire_date_flag'] == 'out_of_range'][['employee_id', 'hire_date', 'source']].head(10))
    # deduped = deduplicate(hris_clean)


    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Input records:           {input_count:,}")
    logger.info(f"  Duration:                {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
