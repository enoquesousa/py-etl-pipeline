"""Application entrypoint: bootstrap schema and execute the ETL pipeline."""

import logging
import os
import sys
import time
from typing import Literal

# Allow running from repository root without installing the package: add src/ to sys.path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC_PATH = os.path.join(ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from py_etl_pipeline.config import load_environment
from py_etl_pipeline.database import get_session, init_db
from py_etl_pipeline.pipeline import run_pipeline
from py_etl_pipeline.retry import retry_db

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)


def main(load_mode: Literal["bulk", "upsert"] = "bulk") -> None:
    """Create missing tables, open a session, run the pipeline, then close.

    Args:
        load_mode: Loading strategy ('bulk' for insert-only, 'upsert' for insert-or-update).
                  Controlled by environment variable LOAD_MODE (default: 'bulk').
    """
    load_environment(os.path.join(ROOT, ".env"))

    # Allow environment variable override
    load_mode_env = os.getenv("LOAD_MODE", "").strip().lower()
    if load_mode_env in ("bulk", "upsert"):
        load_mode = load_mode_env  # type: ignore

    run_scheduled = os.getenv("RUN_SCHEDULED", "").strip().lower() in ("1", "true", "yes")
    interval_minutes = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "60").strip() or "60")
    interval_minutes = max(1, interval_minutes)

    @retry_db
    def _run_once() -> dict[str, int]:
        init_db()
        session = get_session()
        try:
            stats = run_pipeline(session, load_mode=load_mode)
            return stats
        finally:
            session.close()

    def _print_summary(stats: dict[str, int]) -> None:
        print(f"\n{'=' * 60}")
        print("Pipeline Summary:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print(f"{'=' * 60}\n")

    if not run_scheduled:
        print(f"\n{'=' * 60}")
        print(f"Starting ETL Pipeline (load_mode={load_mode})")
        print(f"{'=' * 60}\n")
        _print_summary(_run_once())
        return

    import schedule

    def job() -> None:
        logger = logging.getLogger("scheduler")
        logger.info("Starting scheduled ETL run (load_mode=%s)", load_mode)
        stats = _run_once()
        logger.info("Scheduled ETL run finished: %s", stats)

    schedule.every(interval_minutes).minutes.do(job)

    # Run once on startup, then every interval.
    job()

    logger = logging.getLogger("scheduler")
    logger.info("Scheduler started: every %s minutes", interval_minutes)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
