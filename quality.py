from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REQUIRED_COLUMNS = ("order_id", "order_date", "customer_id", "product_id", "quantity", "unit_price")


@dataclass(frozen=True)
class RuleConfig:
    """Configuration for one quality rule."""

    enabled: bool = True
    threshold: Any = None


@dataclass(frozen=True)
class QualityConfig:
    """Quality policy. Missing rule entries use DEFAULT_RULES."""

    rules: Mapping[str, RuleConfig | Mapping[str, Any] | bool] = field(default_factory=dict)

    def for_rule(self, name: str) -> RuleConfig:
        value = self.rules.get(name, DEFAULT_RULES.get(name, RuleConfig()))
        if isinstance(value, RuleConfig):
            return value
        if isinstance(value, bool):
            return RuleConfig(enabled=value)
        return RuleConfig(**{key: value[key] for key in ("enabled", "threshold") if key in value})


DEFAULT_RULES: dict[str, RuleConfig] = {
    "missing": RuleConfig(),
    "duplicate_primary_key": RuleConfig(),
    "invalid_date": RuleConfig(threshold="%Y-%m-%d"),
    "invalid_number": RuleConfig(),
    "non_positive": RuleConfig(threshold=0),
    "negative_amount": RuleConfig(threshold=0),
}


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
        return sum((self.missing_values, self.duplicate_primary_keys, self.negative_amounts,
                    self.invalid_dates, self.type_errors, self.non_positive_quantities))

    @property
    def valid_rows(self) -> int:
        return max(self.rows_checked - len({issue.row_number for issue in self.issues}), 0)

    @property
    def score(self) -> float:
        if not self.rows_checked:
            return 0.0
        return round(max(0.0, 100.0 - self.total_issues / self.rows_checked * 100.0), 1)

    @property
    def rule_counts(self) -> dict[str, int]:
        return {rule: sum(issue.rule == rule for issue in self.issues)
                for rule in ("missing", "duplicate_primary_key", "negative_amount", "invalid_date", "invalid_number", "non_positive")}


def read_orders(csv_path: str | Path) -> list[dict[str, str]]:
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
        return list(reader)


def _config(value: QualityConfig | Mapping[str, Any] | None) -> QualityConfig:
    if value is None:
        return QualityConfig()
    return value if isinstance(value, QualityConfig) else QualityConfig(value)


def check_quality(rows: list[dict[str, Any]], config: QualityConfig | Mapping[str, Any] | None = None) -> QualitySummary:
    policy = _config(config)
    seen: set[str] = set()
    issues: list[QualityIssue] = []
    counts = {"missing": 0, "duplicate": 0, "negative": 0, "date": 0, "type": 0, "quantity": 0}

    def enabled(rule: str) -> bool:
        return policy.for_rule(rule).enabled

    for index, row in enumerate(rows, start=2):
        if enabled("missing"):
            for column in REQUIRED_COLUMNS:
                if row.get(column) in (None, ""):
                    counts["missing"] += 1
                    issues.append(QualityIssue(index, column, "missing", str(row.get(column, ""))))
        order_id = row.get("order_id")
        key = str(order_id)
        if enabled("duplicate_primary_key") and order_id not in (None, "") and key in seen:
            counts["duplicate"] += 1
            issues.append(QualityIssue(index, "order_id", "duplicate_primary_key", key))
        elif order_id not in (None, ""):
            seen.add(key)
        try:
            quantity = float(row.get("quantity", ""))
            unit_price = float(row.get("unit_price", ""))
            quantity_limit = policy.for_rule("non_positive").threshold
            if enabled("non_positive") and quantity <= (0 if quantity_limit is None else float(quantity_limit)):
                counts["quantity"] += 1
                issues.append(QualityIssue(index, "quantity", "non_positive", str(row.get("quantity", ""))))
            amount_limit = policy.for_rule("negative_amount").threshold
            if enabled("negative_amount") and (quantity * unit_price < (0 if amount_limit is None else float(amount_limit)) or unit_price < (0 if amount_limit is None else float(amount_limit))):
                counts["negative"] += 1
                issues.append(QualityIssue(index, "unit_price", "negative_amount", str(row.get("unit_price", ""))))
        except (TypeError, ValueError):
            if enabled("invalid_number"):
                counts["type"] += 1
                issues.append(QualityIssue(index, "quantity/unit_price", "invalid_number", ""))
        date_format = policy.for_rule("invalid_date").threshold or "%Y-%m-%d"
        if enabled("invalid_date"):
            try:
                datetime.strptime(str(row.get("order_date", "")), str(date_format))
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
        CREATE TABLE IF NOT EXISTS quality_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT NOT NULL,
            total_rows INTEGER NOT NULL, valid_rows INTEGER NOT NULL, issue_count INTEGER NOT NULL,
            score REAL NOT NULL, source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quality_run_rules (
            run_id INTEGER NOT NULL REFERENCES quality_runs(run_id), rule TEXT NOT NULL,
            issue_count INTEGER NOT NULL, PRIMARY KEY (run_id, rule)
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


def run_etl(csv_path: str | Path, db_path: str | Path, config: QualityConfig | Mapping[str, Any] | None = None) -> QualitySummary:
    rows = read_orders(csv_path)
    summary = check_quality(rows, config)
    bad_rows = {issue.row_number for issue in summary.issues}
    valid_rows = [row for i, row in enumerate(rows, start=2) if i not in bad_rows]
    source = Path(csv_path).name
    with sqlite3.connect(db_path) as connection:
        create_schema(connection)
        load_orders(connection, valid_rows, source)
        connection.executemany("INSERT INTO quarantine(source_row, payload, rule, column_name, value, source_file) VALUES (?, ?, ?, ?, ?, ?)", [(i.row_number, json.dumps(rows[i.row_number - 2], ensure_ascii=True), i.rule, i.column, i.value, source) for i in summary.issues])
        run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = connection.execute("INSERT INTO quality_runs(run_at, total_rows, valid_rows, issue_count, score, source) VALUES (?, ?, ?, ?, ?, ?)", (run_at, summary.rows_checked, summary.valid_rows, summary.total_issues, summary.score, source))
        run_id = cursor.lastrowid
        connection.executemany("INSERT INTO quality_run_rules(run_id, rule, issue_count) VALUES (?, ?, ?)", [(run_id, rule, count) for rule, count in summary.rule_counts.items() if count])
        connection.commit()
    return summary


def quality_trend(db_path: str | Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT run_id, run_at, total_rows, valid_rows, issue_count, score, source FROM quality_runs ORDER BY run_at, run_id")]


def rule_distribution(db_path: str | Path, run_id: int | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        query = "SELECT rule, SUM(issue_count) AS issue_count FROM quality_run_rules"
        params: tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            params = (run_id,)
        query += " GROUP BY rule ORDER BY issue_count DESC, rule"
        return [dict(row) for row in connection.execute(query, params)]


if __name__ == "__main__":
    root = Path(__file__).parent
    print(run_etl(root / "data/orders.csv", root / "data/metrics.db"))
