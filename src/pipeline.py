from __future__ import annotations

from datetime import datetime

from config import CONFIG, logger
from ingestion.ingest import ingest_all_sources
from transforms.clean import clean_hris, normalize_currency, format_benefits_ids
from transforms.dedup import deduplicate
from quality.validate import validate
from reporting.visualize import generate_eda_report
from output.export import export_all


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
    benefits_clean = format_benefits_ids(result["benefits"])

    deduped, review_df, ghost_df = deduplicate(hris_clean, payroll_clean)

    quality_report = validate(deduped, ghost_df)

    generate_eda_report(deduped, payroll_clean, benefits_clean, quality_report)

    export_all(deduped, review_df, ghost_df)

    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Input records:           {input_count:,}")
    logger.info(f"  Golden records:          {len(deduped):,}")
    logger.info(f"  Review candidates:       {len(review_df):,}")
    logger.info(f"  Ghost employees:         {len(ghost_df):,}")
    logger.info(f"  Quality checks passed:   {int((quality_report['status'] == 'PASS').sum())}/{len(quality_report)}")
    logger.info(f"  Output dir:              {CONFIG['output_dir']}")
    logger.info(f"  Duration:                {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
