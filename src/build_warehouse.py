"""
Step 1 of the pipeline: load raw CSVs into a SQLite warehouse, build staging and
mart layers, then run data-quality checks. Fails loudly if any 'error' check fails.

Usage:  python src/build_warehouse.py
"""
from pathlib import Path
import sqlite3
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw"
DB = ROOT / "warehouse" / "olist.db"

RAW_TABLES = {
    "raw_orders": "olist_orders_dataset.csv",
    "raw_customers": "olist_customers_dataset.csv",
    "raw_payments": "olist_order_payments_dataset.csv",
    "raw_items": "olist_order_items_dataset.csv",
    "raw_reviews": "olist_order_reviews_dataset.csv",
    "raw_products": "olist_products_dataset.csv",
    "raw_sellers": "olist_sellers_dataset.csv",
    "raw_category_translation": "product_category_name_translation.csv",
}


def load_raw(con: sqlite3.Connection) -> None:
    for table, fname in RAW_TABLES.items():
        df = pd.read_csv(RAW / fname, dtype=str, encoding="utf-8-sig")
        # numeric columns kept numeric so SQL comparisons behave
        for col in ("payment_installments", "payment_value", "payment_sequential",
                    "price", "freight_value", "order_item_id", "review_score"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])
        df.to_sql(table, con, if_exists="replace", index=False)
        print(f"  loaded {table:<26} {len(df):>8,} rows")


def run_sql_file(con: sqlite3.Connection, path: Path) -> None:
    con.executescript(path.read_text())
    print(f"  ran {path.name}")


def run_dq(con: sqlite3.Connection) -> pd.DataFrame:
    sql = (ROOT / "sql" / "dq_checks.sql").read_text()
    res = pd.read_sql(sql, con)
    res["failing_pct"] = (res.failing_rows / res.total_rows * 100).round(2)
    res["status"] = res.apply(
        lambda r: "PASS" if r.failing_rows == 0 else ("FAIL" if r.severity == "error" else "WARN"), axis=1)
    res.to_sql("dq_results", con, if_exists="replace", index=False)
    return res


def main() -> None:
    DB.parent.mkdir(exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    print("Loading raw tables ...")
    load_raw(con)
    print("Building models ...")
    run_sql_file(con, ROOT / "sql" / "01_staging.sql")
    run_sql_file(con, ROOT / "sql" / "02_marts.sql")
    print("Running data-quality checks ...")
    res = run_dq(con)
    print(res[["check_name", "severity", "failing_rows", "total_rows", "failing_pct", "status"]].to_string(index=False))
    out = ROOT / "outputs"
    out.mkdir(exist_ok=True)
    res.to_csv(out / "dq_report.csv", index=False)
    con.close()
    if (res.status == "FAIL").any():
        sys.exit("Pipeline stopped: blocking data-quality check failed.")
    print(f"Warehouse ready: {DB}")


if __name__ == "__main__":
    main()
