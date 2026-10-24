#!/usr/bin/env python
"""
Demo script: Load module showcase with practical examples.

Run from the repository root:
    $env:DATABASE_URL = "sqlite:///demo.db"
    python scripts/demo_load.py

Demonstrates:
1. Bulk insert operations
2. Upsert (insert-or-update) operations
3. Log querying
4. Skip handling for records without keys
"""

import logging
import os
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from py_etl_pipeline.config import load_environment
from py_etl_pipeline.database import get_session, init_db
from py_etl_pipeline.load import load, log_pipeline_event
from py_etl_pipeline.models import LogEntry, Sale

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_SEP = "=" * 70


def demo_bulk_insert(session) -> None:
    """Bulk insert 1000 records."""
    print(f"\n{_SEP}\nDEMO 1: Bulk Insert (1000 records)\n{_SEP}")

    sales = [
        Sale(
            external_id=f"bulk-{i:05d}",
            product_name=f"Product {i % 50}",
            quantity=(i % 20) + 1,
            unit_price=Decimal(f"{(i % 100) + 1}.99"),
        )
        for i in range(1000)
    ]

    result = load(session, sales, mode="bulk")
    session.commit()

    for key, value in result.items():
        print(f"  {key}: {value}")
    print(f"  Total rows in DB: {session.query(Sale).count()}")


def demo_upsert_insert(session) -> None:
    """Upsert 500 new records."""
    print(f"\n{_SEP}\nDEMO 2: Upsert with New Records (500)\n{_SEP}")

    sales = [
        Sale(
            external_id=f"upsert-new-{i:05d}",
            product_name=f"New Product {i}",
            quantity=(i % 15) + 1,
            unit_price=Decimal(f"{(i % 50) * 2}.50"),
        )
        for i in range(500)
    ]

    result = load(session, sales, mode="upsert")
    session.commit()

    for key, value in result.items():
        print(f"  {key}: {value}")
    print(f"  Total rows in DB: {session.query(Sale).count()}")


def demo_upsert_update(session) -> None:
    """Upsert 50 updates + 50 new records."""
    print(f"\n{_SEP}\nDEMO 3: Upsert with Updates (50 updates, 50 new)\n{_SEP}")

    updates = [
        Sale(
            external_id=f"upsert-new-{i:05d}",
            product_name=f"UPDATED Product {i}",
            quantity=99,
            unit_price=Decimal("999.99"),
        )
        for i in range(50)
    ]
    inserts = [
        Sale(
            external_id=f"upsert-new-{i:05d}",
            product_name=f"New Product {i}",
            quantity=i % 10,
            unit_price=Decimal(f"{i}.00"),
        )
        for i in range(50, 100)
    ]

    result = load(session, updates + inserts, mode="upsert")
    session.commit()

    for key, value in result.items():
        print(f"  {key}: {value}")

    sample = session.query(Sale).filter_by(external_id="upsert-new-00000").first()
    if sample:
        print(f"  Verified update - product_name: {sample.product_name}")


def demo_skip_no_key(session) -> None:
    """Upsert records without external_id — they should be skipped."""
    print(f"\n{_SEP}\nDEMO 4: Upsert — Skip Records Without external_id\n{_SEP}")

    valid = [
        Sale(
            external_id=f"skip-demo-{i:05d}",
            product_name=f"Valid {i}",
            quantity=1,
            unit_price=Decimal("10.00"),
        )
        for i in range(25)
    ]
    no_key = [
        Sale(external_id=None, product_name=f"Skipped {i}", quantity=1, unit_price=Decimal("5.00"))
        for i in range(25)
    ]

    result = load(session, valid + no_key, mode="upsert")
    session.commit()

    for key, value in result.items():
        print(f"  {key}: {value}")
    count = session.query(Sale).filter(Sale.external_id.like("skip-demo-%")).count()
    print(f"  Records with skip-demo-* key: {count}")


def demo_manual_logging(session) -> None:
    """Write and query manual log entries."""
    print(f"\n{_SEP}\nDEMO 5: Manual Logging\n{_SEP}")

    log_pipeline_event(
        session,
        "INFO",
        "Processed vendor ABC monthly export (5000 records)",
        source="vendor_sync.abc",
    )
    log_pipeline_event(
        session, "WARNING", "23 records skipped — missing external_id", source="vendor_sync.abc"
    )
    session.flush()

    logs = session.query(LogEntry).filter_by(source="vendor_sync.abc").all()
    print(f"  Manual logs created: {len(logs)}")
    for log in logs:
        print(f"  [{log.level}] {log.message}")


def demo_log_analysis(session) -> None:
    """Summarise all pipeline log entries."""
    print(f"\n{_SEP}\nDEMO 6: Log Analysis\n{_SEP}")

    logs = session.query(LogEntry).filter_by(source="pipeline.load").all()
    print(f"  Total load operations logged: {len(logs)}")
    print("  Recent logs:")
    for log in logs[-5:]:
        print(f"    [{log.level}] {log.created_at.strftime('%H:%M:%S')}: {log.message}")

    info_count = session.query(LogEntry).filter_by(level="INFO").count()
    error_count = session.query(LogEntry).filter_by(level="ERROR").count()
    print(f"  INFO: {info_count}  ERROR: {error_count}")


def main() -> None:
    load_environment(os.path.join(ROOT, ".env"))
    init_db()
    session = get_session()

    try:
        demo_bulk_insert(session)
        demo_upsert_insert(session)
        demo_upsert_update(session)
        demo_skip_no_key(session)
        demo_manual_logging(session)
        demo_log_analysis(session)

        print(f"\n{_SEP}\nFINAL SUMMARY\n{_SEP}")
        print(f"  Total Sales : {session.query(Sale).count()}")
        print(f"  Total Logs  : {session.query(LogEntry).count()}")
        print("  Demo completed successfully!")

    finally:
        session.close()


if __name__ == "__main__":
    main()
