from __future__ import annotations

import os

# Allow running from repository root without installing the package: add src/ to sys.path
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from py_etl_pipeline.config import load_environment  # noqa: E402
from py_etl_pipeline.database import get_session, init_db  # noqa: E402
from py_etl_pipeline.models import Sale  # noqa: E402
from py_etl_pipeline.pipeline import run_pipeline  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    load_environment(ROOT / ".env")
    # Fallback to SQLite so anyone can validate quickly.
    # If you want PostgreSQL, set DATABASE_URL in your environment/.env.
    force_sqlite = os.getenv("VALIDATE_FORCE_SQLITE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not os.getenv("DATABASE_URL") or force_sqlite:
        db_path = ROOT / "validate.db"
        if db_path.exists():
            db_path.unlink()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    csv1 = ROOT / "data" / "_validate_sales_1.csv"
    csv2 = ROOT / "data" / "_validate_sales_2.csv"

    # Dataset 1: initial insert
    _write_csv(
        csv1,
        [
            {
                "Product Name": "Laptop",
                "Quantity": "2",
                "Unit Price": "100.00",
                "Sold At": "2026-05-01T10:30:00Z",
                "External ID": "ext-1",
            },
            {
                "Product Name": "Mouse",
                "Quantity": "1",
                "Unit Price": "20.00",
                "Sold At": "2026-05-01T11:00:00Z",
                "External ID": "ext-2",
            },
        ],
    )

    # Dataset 2: one update (ext-1), one duplicate inside same batch (last wins), one new row
    _write_csv(
        csv2,
        [
            {
                "Product Name": "Laptop PRO",
                "Quantity": "3",
                "Unit Price": "110.00",
                "Sold At": "2026-05-02T10:30:00Z",
                "External ID": "ext-1",
            },
            {
                "Product Name": "Laptop PRO (duplicate, should win)",
                "Quantity": "4",
                "Unit Price": "120.00",
                "Sold At": "2026-05-02T10:31:00Z",
                "External ID": "ext-1",
            },
            {
                "Product Name": "Keyboard",
                "Quantity": "2",
                "Unit Price": "50.00",
                "Sold At": "2026-05-02T12:00:00Z",
                "External ID": "ext-3",
            },
            {
                "Product Name": "No External ID (should be skipped in upsert)",
                "Quantity": "1",
                "Unit Price": "1.00",
                "Sold At": "2026-05-02T12:30:00Z",
                "External ID": "",
            },
        ],
    )

    init_db()
    session = get_session()
    try:
        print("\n== Bulk insert run (csv1) ==")
        os.environ["SALES_CSV_PATH"] = str(csv1)
        bulk_stats = run_pipeline(session, load_mode="bulk")
        session.commit()
        print("Stats:", bulk_stats)

        print("\n== Upsert run (csv2, key=external_id) ==")
        os.environ["SALES_CSV_PATH"] = str(csv2)
        upsert_stats = run_pipeline(session, load_mode="upsert")
        session.commit()
        print("Stats:", upsert_stats)

        rows = session.scalars(select(Sale).order_by(Sale.external_id, Sale.id)).all()
        print("\n== Current sales rows ==")
        for r in rows:
            print(
                f"- id={r.id} external_id={r.external_id!r} "
                f"product_name={r.product_name!r} qty={r.quantity} "
                f"unit_price={r.unit_price} sold_at={r.sold_at}"
            )
    finally:
        session.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
