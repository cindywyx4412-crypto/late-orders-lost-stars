"""
A minimal metrics semantic layer (same idea as dbt MetricFlow / LookML, ~100 lines).

Metrics live in metrics/metrics.yml. This module validates requests and compiles
them to SQL so every consumer (dashboard, analysis, experiment design) computes a
metric the same way.

    from semantic_layer import SemanticLayer
    sl = SemanticLayer()
    sl.query(["gmv", "late_delivery_rate"], by=["purchase_month"])
"""
from pathlib import Path
import sqlite3

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


class SemanticLayer:
    def __init__(self, spec_path: Path = ROOT / "metrics" / "metrics.yml",
                 db_path: Path = ROOT / "warehouse" / "olist.db"):
        spec = yaml.safe_load(Path(spec_path).read_text())
        self.models = spec["models"]
        self.metrics = spec["metrics"]
        self.db_path = db_path

    # ---------- compilation ----------
    def _metric_expr(self, name: str) -> str:
        m = self.metrics[name]
        flt = m.get("filter")
        def gate(expr: str) -> str:
            return f"CASE WHEN {flt} THEN ({expr}) END" if flt else f"({expr})"
        if m["type"] == "count":
            return f"SUM({gate('1')})"
        if m["type"] == "sum":
            return f"SUM({gate(m['expr'])})"
        if m["type"] == "ratio":
            return (f"1.0 * SUM({gate(str(m['numerator']))}) / "
                    f"NULLIF(SUM({gate(str(m['denominator']))}), 0)")
        raise ValueError(f"unknown metric type {m['type']}")

    def compile(self, metrics: list[str], by: list[str] | None = None,
                where: str | None = None) -> str:
        by = by or []
        unknown = [m for m in metrics if m not in self.metrics]
        if unknown:
            raise KeyError(f"undefined metrics: {unknown}")
        models = {self.metrics[m]["model"] for m in metrics}
        if len(models) != 1:
            raise ValueError(f"metrics span several models {models}; query them separately")
        model = models.pop()
        allowed = self.models[model]["dimensions"]
        bad = [d for d in by if d not in allowed]
        if bad:
            raise ValueError(f"dimensions {bad} not allowed for {model}; allowed: {allowed}")
        filters = [self.models[model].get("default_filter")]
        if where:
            filters.append(where)
        where_sql = " AND ".join(f"({f})" for f in filters if f)
        select = by + [f"{self._metric_expr(m)} AS {m}" for m in metrics]
        sql = f"SELECT {', '.join(select)}\nFROM {model}"
        if where_sql:
            sql += f"\nWHERE {where_sql}"
        if by:
            sql += f"\nGROUP BY {', '.join(by)}\nORDER BY {', '.join(by)}"
        return sql

    # ---------- execution ----------
    def query(self, metrics: list[str], by: list[str] | None = None,
              where: str | None = None) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql(self.compile(metrics, by, where), con)

    def catalog(self) -> pd.DataFrame:
        return pd.DataFrame([{"metric": k, "model": v["model"], "type": v["type"],
                              "description": v["description"]} for k, v in self.metrics.items()])


if __name__ == "__main__":
    sl = SemanticLayer()
    print(sl.catalog().to_string(index=False))
    print()
    print(sl.compile(["gmv", "late_delivery_rate"], by=["purchase_month"]))
    print(sl.query(["orders", "gmv", "aov", "cancel_rate", "late_delivery_rate",
                    "avg_review_score", "low_review_rate", "recon_break_rate"]).T)
    print(sl.query(["repurchase_rate_180d"]))
