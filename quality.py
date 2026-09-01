from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = ("order_id", "order_date", "customer_id", "product_id", "quantity", "unit_price")


@dataclass(frozen=True)
class QualityIssue:
    row_number: int
    column: str
    rule: str
    value: str
    severity: str = "error"


@dataclass(frozen=True)
class QualitySummary:
    rows_checked: int
    missing_values: int
    duplicate_primary_keys: int
    negative_amounts: int
    invalid_dates: int
    type_errors: int = 0
    non_positive_quantities: int = 0
    issues: tuple[QualityIssue, ...] = ()

    @property
    def total_issues(self) -> int:
        return self.missing_values + self.duplicate_primary_keys + self.negative_amounts + self.invalid_dates + self.type_errors + self.non_positive_quantities

    @property
    def valid_rows(self) -> int:
        return max(self.rows_checked - len({issue.row_number for issue in self.issues}), 0)

    @property
    def score(self) -> float:
        if not self.rows_checked:
            return 0.0
        return round(max(0.0, 100.0 - self.total_issues / self.rows_checked * 100.0), 1)


def read_orders(csv_path: str | Path) -> list[dict[str, str]]:
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def check_quality(rows: list[dict[str, Any]]) -> QualitySummary:
    seen: set[str] = set()
    issues: list[QualityIssue] = []
    counts = {"missing": 0, "duplicate": 0, "negative": 0, "date": 0, "type": 0, "quantity": 0}
    for index, row in enumerate(rows, start=2):
        for column in REQUIRED_COLUMNS:
            if row.get(column) in (None, ""):
                counts["missing"] += 1
                issues.append(QualityIssue(index, column, "missing", str(row.get(column, ""))))
        order_id = row.get("order_id")
        key = str(order_id)
        if order_id not in (None, "") and key in seen:
            counts["duplicate"] += 1
            issues.append(QualityIssue(index, "order_id", "duplicate_primary_key", key))
        elif order_id not in (None, ""):
            seen.add(key)
        try:
            quantity = float(row.get("quantity", ""))
            unit_price = float(row.get("unit_price", ""))
            if quantity <= 0:
                counts["quantity"] += 1
                issues.append(QualityIssue(index, "quantity", "non_positive", str(row.get("quantity", ""))))
            if quantity * unit_price < 0 or unit_price < 0:
                counts["negative"] += 1
                issues.append(QualityIssue(index, "unit_price", "negative_amount", str(row.get("unit_price", ""))))
        except (TypeError, ValueError):
            counts["type"] += 1
            issues.append(QualityIssue(index, "quantity/unit_price", "invalid_number", ""))
        try:
            datetime.strptime(str(row.get("order_date", "")), "%Y-%m-%d")
        except (TypeError, ValueError):
            counts["date"] += 1
            issues.append(QualityIssue(index, "order_date", "invalid_date", str(row.get("order_date", ""))))
    return QualitySummary(len(rows), counts["missing"], counts["duplicate"], counts["negative"], counts["date"], counts["type"], counts["quantity"], tuple(issues))


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS quarantine;
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY, order_date TEXT NOT NULL, customer_id TEXT NOT NULL,
            product_id TEXT NOT NULL, quantity REAL NOT NULL, unit_price REAL NOT NULL,
            source_file TEXT NOT NULL, source_row INTEGER NOT NULL, loaded_at TEXT NOT NULL
        );
        CREATE TABLE quarantine (
            source_row INTEGER NOT NULL, payload TEXT NOT NULL, rule TEXT NOT NULL,
            column_name TEXT NOT NULL, value TEXT, source_file TEXT NOT NULL
        );
    """)
    connection.commit()


def load_orders(connection: sqlite3.Connection, rows: list[dict[str, str]], source_file: str = "orders.csv") -> int:
    connection.executemany(
        "INSERT INTO orders(order_id, order_date, customer_id, product_id, quantity, unit_price, source_file, source_row, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        [(int(r["order_id"]), r["order_date"], r["customer_id"], r["product_id"], float(r["quantity"]), float(r["unit_price"]), source_file, i) for i, r in enumerate(rows, start=2)],
    )
    connection.commit()
    return len(rows)


def run_etl(csv_path: str | Path, db_path: str | Path) -> QualitySummary:
    rows = read_orders(csv_path)
    summary = check_quality(rows)
    bad_rows = {issue.row_number for issue in summary.issues}
    valid_rows = [row for i, row in enumerate(rows, start=2) if i not in bad_rows]
    with sqlite3.connect(db_path) as connection:
        create_schema(connection)
        load_orders(connection, valid_rows, Path(csv_path).name)
        connection.executemany("INSERT INTO quarantine(source_row, payload, rule, column_name, value, source_file) VALUES (?, ?, ?, ?, ?, ?)", [(i.row_number, str(rows[i.row_number - 2]), i.rule, i.column, i.value, Path(csv_path).name) for i in summary.issues])
        connection.commit()
    return summary


if __name__ == "__main__":
    root = Path(__file__).parent
    print(run_etl(root / "data/orders.csv", root / "data/metrics.db"))
