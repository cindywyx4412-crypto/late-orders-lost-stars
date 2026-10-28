"""
Step 3: design (not run) an A/B test for the top recommendation, using real
historical baselines, an analytic power calculation, and simulations that resample
real historical orders to check the false-positive rate (A/A) and achieved power.

Test: "Proactive delay alerts" for orders the risk model scores in the top 30%.
Treatment: at payment approval, the customer sees a realistic ETA and gets a status
update if the order slips; the seller gets an escalation. Control: current experience.

Usage:  python src/experiment_design.py   (run after analysis.py)
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
ALPHA, POWER, MDE_PP, SIMS = 0.05, 0.80, 2.0, 2000
RNG = np.random.default_rng(42)


def n_per_arm(p0: float, abs_drop: float) -> int:
    es = proportion_effectsize(p0, p0 - abs_drop)
    return int(np.ceil(NormalIndPower().solve_power(effect_size=abs(es), alpha=ALPHA, power=POWER, ratio=1)))


def main():
    F = json.loads((OUT / "findings.json").read_text())
    rm = F["risk_model"]
    pool = pd.read_csv(OUT / "targeted_pool.csv")          # real historical targeted orders (Apr-Aug 2018)
    y = pool.is_low_review.to_numpy().astype(int)
    p0 = y.mean()
    monthly = rm["top3_deciles_orders_per_month"]

    # ---- analytic power curve ----
    rows = []
    for mde in [1.0, 1.5, 2.0, 2.5, 3.0]:
        n = n_per_arm(p0, mde / 100)
        rows.append({"mde_pp": mde, "relative_mde_pct": round(mde / 100 / p0 * 100),
                     "n_per_arm": n, "total_n": 2 * n,
                     "weeks_at_2018_volume": round(2 * n / monthly * 52 / 12, 1)})
    curve = pd.DataFrame(rows)
    curve.to_csv(OUT / "power_curve.csv", index=False)
    n = int(curve.loc[curve.mde_pp == MDE_PP, "n_per_arm"].iloc[0])

    # ---- simulations: resample real orders into two arms ----
    flip_prob = (MDE_PP / 100) / p0     # share of treatment-arm low reviews turned non-low => MDE_PP absolute drop
    false_pos = detected = 0
    for _ in range(SIMS):
        a, b = RNG.choice(y, n), RNG.choice(y, n)
        false_pos += proportions_ztest([a.sum(), b.sum()], [n, n])[1] < ALPHA          # A/A: no true effect
        t, c = RNG.choice(y, n), RNG.choice(y, n)
        t = np.where((t == 1) & (RNG.random(n) < flip_prob), 0, t)                     # inject the effect
        detected += proportions_ztest([t.sum(), c.sum()], [n, n])[1] < ALPHA

    row = curve.loc[curve.mde_pp == MDE_PP].iloc[0]
    design = {
        "name": "Proactive delay alerts for high-risk orders",
        "hypothesis": "Setting a realistic ETA and alerting customers before a slip lowers 1-2 star reviews "
                      "among orders the risk model flags as likely late.",
        "unit_of_randomization": "customer (hash of customer_unique_id) so repeat buyers stay in one arm",
        "eligibility": "orders scored in the top 3 risk deciles at payment approval "
                       f"(these held {rm['top3_deciles_capture_pct']}% of late orders out-of-time)",
        "primary_metric": "low_review_rate (from the metric registry)",
        "baseline_pct": round(p0 * 100, 1), "baseline_source_orders": len(y),
        "mde_pp": MDE_PP, "relative_mde_pct": int(row.relative_mde_pct),
        "alpha": ALPHA, "power": POWER, "n_per_arm": n, "total_n": int(row.total_n),
        "eligible_orders_per_month_2018": monthly,
        "duration_weeks_at_2018_volume": float(row.weeks_at_2018_volume),
        "guardrails": ["cancel_rate", "avg delivery days", "support contacts per order",
                       "alert cost per order", "sample ratio mismatch (chi-square p < 0.001 = stop)"],
        "secondary_metrics": ["avg_review_score", "late_delivery_rate"],
        "decision_rule": "ship if low_review_rate falls at p < 0.05 and no guardrail worsens by more than 2%",
        "simulation_checks": {
            "simulations": SIMS,
            "aa_false_positive_rate_pct": round(false_pos / SIMS * 100, 1),
            "simulated_power_pct": round(detected / SIMS * 100, 1),
            "method": "resample real Apr-Aug 2018 targeted orders with replacement; two-proportion z-test",
        },
        "risks": ["review lag: reviews arrive after delivery, so read results 30 days after enrollment closes",
                  "interference: sellers serve both arms; escalations may also help control orders (bias toward null)",
                  "novelty: run whole weeks and check the effect by week"],
    }
    (OUT / "experiment_design.json").write_text(json.dumps(design, indent=2))
    print(curve.to_string(index=False))
    print(json.dumps(design, indent=2))


if __name__ == "__main__":
    main()
