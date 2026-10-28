"""
Step 4: render outputs/ into a single self-contained HTML report + dashboard.
Every number on the page is read from outputs/*.json|csv (no hand-typed figures).

Usage:  python src/build_dashboard.py
"""
from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def records(name):
    return json.loads(pd.read_csv(OUT / f"{name}.csv").to_json(orient="records"))


def main():
    data = {
        "f": json.loads((OUT / "findings.json").read_text()),
        "exp": json.loads((OUT / "experiment_design.json").read_text()),
        "monthly": records("monthly_metrics"),
        "late": records("late_buckets"),
        "pay": records("payment_methods"),
        "lag": records("approval_lag_late"),
        "inst": records("installments"),
        "dec": records("risk_deciles"),
        "power": records("power_curve"),
        "dq": records("dq_report"),
    }
    tpl = (ROOT / "src" / "dashboard_template.html").read_text()
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    (OUT / "dashboard.html").write_text(html)
    print(f"wrote {OUT / 'dashboard.html'} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
