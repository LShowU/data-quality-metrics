import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from quality import check_quality, read_orders, run_etl

ROOT = Path(__file__).parents[1]
CSV = ROOT / "data" / "orders.csv"


def test_sample_quality_is_clean():
    summary = check_quality(read_orders(CSV))
    assert summary.rows_checked == 10
    assert summary.valid_rows == 10
    assert summary.total_issues == 0
    assert summary.score == 100.0


def test_quality_rules_detect_issues_and_samples():
    rows = [
        {"order_id": "1", "order_date": "bad", "customer_id": "", "product_id": "P", "quantity": "1", "unit_price": "-2"},
        {"order_id": "1", "order_date": "2024-01-01", "customer_id": "C", "product_id": "P", "quantity": "x", "unit_price": "2"},
        {"order_id": "2", "order_date": "2024-01-02", "customer_id": "C", "product_id": "P", "quantity": "0", "unit_price": "2"},
    ]
    summary = check_quality(rows)
    assert summary.missing_values == 1
    assert summary.duplicate_primary_keys == 1
    assert summary.negative_amounts == 1
    assert summary.invalid_dates == 1
    assert summary.type_errors == 1
    assert summary.non_positive_quantities == 1
    assert summary.valid_rows == 0
    assert summary.score < 100
    assert any(issue.rule == "invalid_date" for issue in summary.issues)


def test_etl_quarantines_bad_rows_and_loads_metrics(tmp_path):
    db = tmp_path / "metrics.db"
    source = tmp_path / "orders.csv"
    source.write_text("order_id,order_date,customer_id,product_id,quantity,unit_price\n1,2024-01-01,C1,P1,2,10\n1,bad,,P2,1,-3\n", encoding="utf-8")
    summary = run_etl(source, db)
    with sqlite3.connect(db) as connection:
        loaded = connection.execute("SELECT COUNT(*), ROUND(SUM(quantity * unit_price), 2), source_file, source_row FROM orders").fetchone()
        quarantined = connection.execute("SELECT COUNT(*), COUNT(DISTINCT source_row) FROM quarantine").fetchone()
    assert summary.total_issues >= 3
    assert loaded == (1, 20.0, "orders.csv", 2)
    assert quarantined == (4, 1)


def test_etl_sample_is_repeatable(tmp_path):
    db = tmp_path / "metrics.db"
    run_etl(CSV, db)
    run_etl(CSV, db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (10,)
        assert connection.execute("SELECT COUNT(*) FROM quarantine").fetchone() == (0,)
