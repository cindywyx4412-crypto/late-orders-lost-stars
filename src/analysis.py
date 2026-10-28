"""
Step 2: business analysis. Every headline number is written to outputs/findings.json
so the report, dashboard and resume bullets all cite the same source.

Usage:  python src/analysis.py
"""
from pathlib import Path
import json
import sqlite3
import sys

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from semantic_layer import SemanticLayer   # noqa: E402
from review_themes import tag              # noqa: E402

DB = ROOT / "warehouse" / "olist.db"
OUT = ROOT / "outputs"
WINDOW = "purchase_month BETWEEN '2017-01' AND '2018-08'"
F: dict = {}   # findings


def q(con, sql):
    return pd.read_sql(sql, con)


def pct(x, d=1):
    return round(float(x) * 100, d)


def main():
    OUT.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    sl = SemanticLayer()

    # ---------------- 1. headline metrics (semantic layer) ----------------
    h = sl.query(["orders", "gmv", "aov", "cancel_rate", "late_delivery_rate",
                  "avg_review_score", "low_review_rate", "recon_break_rate",
                  "payment_approval_rate_24h", "installment_share"]).iloc[0]
    F["headline"] = {
        "window": "Jan 2017 - Aug 2018 (20 complete months)",
        "orders": int(h.orders), "gmv_brl": round(h.gmv), "aov_brl": round(h.aov, 2),
        "cancel_rate_pct": pct(h.cancel_rate, 2), "late_delivery_rate_pct": pct(h.late_delivery_rate),
        "avg_review_score": round(h.avg_review_score, 2), "low_review_rate_pct": pct(h.low_review_rate),
        "payment_approval_24h_pct": pct(h.payment_approval_rate_24h),
        "installment_share_of_card_orders_pct": pct(h.installment_share),
        "sellers": int(q(con, "SELECT COUNT(*) FROM dim_sellers WHERE gmv IS NOT NULL").iloc[0, 0]),
        "customers": int(q(con, f"SELECT COUNT(DISTINCT customer_unique_id) FROM fct_orders WHERE {WINDOW}").iloc[0, 0]),
        "repurchase_rate_180d_pct": pct(sl.query(["repurchase_rate_180d"]).iloc[0, 0]),
        "metrics_defined": len(sl.metrics),
    }
    monthly = sl.query(["orders", "gmv", "late_delivery_rate", "low_review_rate", "payment_approval_rate_24h"],
                       by=["purchase_month"])
    monthly.to_csv(OUT / "monthly_metrics.csv", index=False)

    # ---------------- 2. data quality + reconciliation ----------------
    dq = q(con, "SELECT * FROM dq_results")
    F["data_quality"] = {
        "checks": len(dq), "blocking_failures": int((dq.status == "FAIL").sum()),
        "warnings": int((dq.status == "WARN").sum()),
        "rows_flagged": {r.check_name: int(r.failing_rows) for r in dq.itertuples() if r.failing_rows > 0},
    }
    rec = q(con, f"""SELECT primary_payment_type, max_installments, recon_diff FROM fct_orders
                     WHERE recon_diff IS NOT NULL AND ABS(recon_diff) > 1""")
    inst_over = int(((rec.primary_payment_type == "credit_card") & (rec.max_installments >= 2) & (rec.recon_diff > 0)).sum())
    F["reconciliation"] = {
        "orders_checked": int(q(con, "SELECT COUNT(*) FROM fct_orders WHERE recon_diff IS NOT NULL").iloc[0, 0]),
        "breaks": len(rec), "break_rate_pct": pct(h.recon_break_rate, 2),
        "breaks_from_installment_interest": inst_over,
        "share_explained_by_installment_interest_pct": pct(inst_over / len(rec)),
        "total_abs_diff_brl": round(float(rec.recon_diff.abs().sum()), 2),
        "boleto_breaks": int((rec.primary_payment_type == "boleto").sum()),
    }

    # ---------------- 3. late delivery -> reviews ----------------
    d = q(con, f"SELECT * FROM fct_orders WHERE {WINDOW} AND is_late IS NOT NULL")
    top_cats = d.primary_category.value_counts().index[:20]
    d["cat"] = np.where(d.primary_category.isin(top_cats), d.primary_category, "other")
    d["log_value"] = np.log1p(d.items_value.fillna(0))
    d["slow_pay"] = (d.approval_lag_hours > 24).astype(int)
    d["boleto"] = (d.primary_payment_type == "boleto").astype(int)
    buckets = pd.cut(d.days_vs_estimate, [-1e9, 0, 3, 7, 1e9], labels=["On time", "1-3 days late", "4-7 days late", "8+ days late"])
    lb = d.groupby(buckets, observed=True).agg(orders=("order_id", "size"), avg_review=("review_score", "mean"),
                                               low_review_rate=("is_low_review", "mean")).reset_index(names="bucket")
    lb.to_csv(OUT / "late_buckets.csv", index=False)
    FE = "log_value + C(customer_state) + C(cat) + C(purchase_month)"
    m1 = smf.ols(f"is_low_review ~ is_late + {FE}", d.dropna(subset=["is_low_review"])).fit(cov_type="HC1")
    ci1 = m1.conf_int().loc["is_late"]
    F["late_to_reviews"] = {
        "low_review_on_time_pct": pct(d.loc[d.is_late == 0, "is_low_review"].mean()),
        "low_review_late_pct": pct(d.loc[d.is_late == 1, "is_low_review"].mean()),
        "avg_review_on_time": round(d.loc[d.is_late == 0, "review_score"].mean(), 2),
        "avg_review_late": round(d.loc[d.is_late == 1, "review_score"].mean(), 2),
        "low_review_8plus_days_late_pct": pct(lb.loc[lb.bucket == "8+ days late", "low_review_rate"].iloc[0]),
        "adjusted_effect_pp": round(m1.params["is_late"] * 100, 1),
        "adjusted_effect_ci_pp": [round(ci1[0] * 100, 1), round(ci1[1] * 100, 1)],
        "controls": "customer state, top-20 category, log order value, purchase month; HC1 robust SE",
        "n": int(m1.nobs),
    }

    # ---------------- 4. late delivery -> repurchase (null result, reported honestly) ----------------
    c = q(con, """SELECT * FROM dim_customers WHERE first_purchase_month BETWEEN '2017-01' AND '2018-02'
                  AND first_order_late IS NOT NULL""")
    c["cat"] = np.where(c.first_category.isin(top_cats), c.first_category, "other")
    c["log_value"] = np.log1p(c.first_items_value.fillna(0))
    m3 = smf.ols("repurchased_180d ~ first_order_late + log_value + C(customer_state) + C(cat) + C(first_purchase_month)",
                 c).fit(cov_type="HC1")
    F["late_to_repurchase"] = {
        "repurchase_on_time_pct": pct(c.loc[c.first_order_late == 0, "repurchased_180d"].mean(), 2),
        "repurchase_late_pct": pct(c.loc[c.first_order_late == 1, "repurchased_180d"].mean(), 2),
        "adjusted_effect_pp": round(m3.params["first_order_late"] * 100, 2),
        "p_value": round(float(m3.pvalues["first_order_late"]), 3),
        "conclusion": "not statistically significant; repeat purchase is rare (~3%) on this marketplace",
    }

    # ---------------- 5. payments: approval lag & installments ----------------
    pay = q(con, f"""SELECT primary_payment_type AS payment_type, COUNT(*) AS orders,
        SUM(CASE WHEN is_canceled=0 THEN items_value END) AS gmv,
        AVG(approval_lag_hours) AS avg_approval_hours, AVG(approval_lag_hours <= 24) AS approved_24h,
        AVG(is_late) AS late_rate, AVG(delivery_days) AS avg_delivery_days, AVG(is_canceled) AS cancel_rate
        FROM fct_orders WHERE {WINDOW} AND primary_payment_type != 'unknown' GROUP BY 1 ORDER BY orders DESC""")
    pay["order_share"] = pay.orders / pay.orders.sum()
    pay["gmv_share"] = pay.gmv / pay.gmv.sum()
    pay.to_csv(OUT / "payment_methods.csv", index=False)
    lag = d.groupby(pd.cut(d.approval_lag_hours, [-1, 24, 48, 72, 1e9], labels=["<=1 day", "1-2 days", "2-3 days", ">3 days"]),
                    observed=True).agg(orders=("order_id", "size"), late_rate=("is_late", "mean")).reset_index(names="approval_lag")
    lag.to_csv(OUT / "approval_lag_late.csv", index=False)
    m2 = smf.ols(f"is_late ~ slow_pay + {FE}", d).fit(cov_type="HC1")
    ci2 = m2.conf_int().loc["slow_pay"]
    base_fast = d.loc[d.slow_pay == 0, "is_late"].mean()
    bol = pay.set_index("payment_type").loc["boleto"]
    cc = pay.set_index("payment_type").loc["credit_card"]
    F["payments"] = {
        "boleto_order_share_pct": pct(bol.order_share), "credit_card_order_share_pct": pct(cc.order_share),
        "boleto_avg_approval_hours": round(bol.avg_approval_hours, 1), "card_avg_approval_hours": round(cc.avg_approval_hours, 1),
        "boleto_approved_24h_pct": pct(bol.approved_24h), "card_approved_24h_pct": pct(cc.approved_24h),
        "late_rate_fast_approval_pct": pct(base_fast), "late_rate_slow_approval_pct": pct(d.loc[d.slow_pay == 1, "is_late"].mean()),
        "slow_pay_adjusted_effect_pp": round(m2.params["slow_pay"] * 100, 2),
        "slow_pay_adjusted_effect_ci_pp": [round(ci2[0] * 100, 2), round(ci2[1] * 100, 2)],
        "slow_pay_relative_increase_pct": round(m2.params["slow_pay"] / base_fast * 100),
        "slow_pay_orders_share_pct": pct(d.slow_pay.mean()),
    }
    inst = q(con, f"""SELECT CASE WHEN max_installments=1 THEN '1x' WHEN max_installments<=3 THEN '2-3x'
        WHEN max_installments<=6 THEN '4-6x' ELSE '7x+' END AS installments,
        COUNT(*) AS orders, AVG(items_value) AS aov, SUM(items_value) AS gmv
        FROM fct_orders WHERE {WINDOW} AND primary_payment_type='credit_card' AND is_canceled=0 GROUP BY 1 ORDER BY 1""")
    inst["order_share"] = inst.orders / inst.orders.sum()
    inst["gmv_share"] = inst.gmv / inst.gmv.sum()
    inst.to_csv(OUT / "installments.csv", index=False)
    i7 = inst.set_index("installments").loc["7x+"]
    i1 = inst.set_index("installments").loc["1x"]
    F["installments"] = {
        "seven_plus_order_share_pct": pct(i7.order_share), "seven_plus_gmv_share_pct": pct(i7.gmv_share),
        "seven_plus_aov_brl": round(i7.aov, 2), "single_payment_aov_brl": round(i1.aov, 2),
        "aov_multiple": round(i7.aov / i1.aov, 1),
    }

    # ---------------- 6. seller concentration & risk tiers ----------------
    s = q(con, "SELECT * FROM dim_sellers WHERE gmv IS NOT NULL").sort_values("gmv", ascending=False).reset_index(drop=True)
    n = len(s)
    top10 = s.gmv[: int(np.ceil(n * 0.10))].sum() / s.gmv.sum()
    plat_low, plat_late = h.low_review_rate, h.late_delivery_rate
    el = s[s.orders >= 30].copy()
    el["at_risk"] = (el.low_review_rate >= 1.5 * plat_low) | (el.late_rate >= 1.5 * plat_late)
    risk = el[el.at_risk]
    o = q(con, f"SELECT primary_seller_id, is_low_review, is_late FROM fct_orders WHERE {WINDOW}")
    o["risk"] = o.primary_seller_id.isin(risk.seller_id)
    # impact sizing: bring at-risk sellers' late rate down to the platform rate
    excess_late = float(((risk.late_rate - plat_late).clip(lower=0) * risk.orders).sum())
    F["sellers"] = {
        "sellers": n, "top10pct_gmv_share_pct": pct(top10),
        "eligible_sellers_30plus_orders": len(el), "at_risk_sellers": len(risk),
        "risk_rule": "30+ orders and (late rate >= 1.5x platform OR low-review rate >= 1.5x platform)",
        "at_risk_order_share_pct": pct(o.risk.mean()),
        "at_risk_share_of_late_pct": pct(o.loc[o.is_late == 1, "risk"].mean()),
        "at_risk_share_of_low_reviews_pct": pct(o.loc[o.is_low_review == 1, "risk"].mean()),
        "at_risk_gmv_brl": round(float(risk.gmv.sum())),
        "excess_late_orders_vs_platform": round(excess_late),
        "low_reviews_avoidable_if_fixed": round(excess_late * m1.params["is_late"]),
    }
    el.to_csv(OUT / "seller_scorecard.csv", index=False)

    # ---------------- 7. late-delivery risk model (out-of-time validation) ----------------
    md = q(con, f"""SELECT o.*, s.seller_state,
        julianday(o.estimated_delivery_date) - julianday(o.purchase_ts) AS promised_days
        FROM fct_orders o LEFT JOIN raw_sellers s ON s.seller_id = o.primary_seller_id
        WHERE o.{WINDOW} AND o.is_late IS NOT NULL""")
    md["same_state"] = (md.customer_state == md.seller_state).astype(int)
    md["freight_ratio"] = md.freight_value / md.items_value
    ts = pd.to_datetime(md.purchase_ts)
    md["month_num"], md["dow"] = ts.dt.month, ts.dt.dayofweek
    cats = ["customer_state", "seller_state", "primary_category", "primary_payment_type"]
    for col in cats:
        md[col] = md[col].astype("category")
    feats = cats + ["same_state", "freight_value", "items_value", "freight_ratio", "item_count", "seller_count",
                    "approval_lag_hours", "promised_days", "month_num", "dow", "max_installments"]
    tr, te = md[md.purchase_month <= "2018-03"], md[md.purchase_month >= "2018-04"].copy()
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, categorical_features="from_dtype",
                                         random_state=0).fit(tr[feats], tr.is_late)
    te["p"] = clf.predict_proba(te[feats])[:, 1]
    te["decile"] = pd.qcut(te.p.rank(method="first"), 10, labels=False)
    dec = te.groupby("decile").agg(orders=("order_id", "size"), late_rate=("is_late", "mean"),
                                   low_review_rate=("is_low_review", "mean")).reset_index()
    dec.to_csv(OUT / "risk_deciles.csv", index=False)
    top = te[te.decile == 9]
    top3 = te[te.decile >= 7]
    # order-level pool reused by experiment_design.py for A/A and power simulations
    top3.loc[top3.is_low_review.notna(), ["order_id", "decile", "is_late", "is_low_review"]].to_csv(
        OUT / "targeted_pool.csv", index=False)
    F["risk_model"] = {
        "model": "HistGradientBoosting, features known at payment approval",
        "train_window": "2017-01 to 2018-03", "test_window": "2018-04 to 2018-08",
        "train_n": len(tr), "test_n": len(te), "auc": round(roc_auc_score(te.is_late, te.p), 3),
        "test_late_rate_pct": pct(te.is_late.mean()),
        "top_decile_late_rate_pct": pct(top.is_late.mean()),
        "top_decile_lift": round(top.is_late.mean() / te.is_late.mean(), 1),
        "top_decile_capture_pct": pct(top.is_late.sum() / te.is_late.sum()),
        "top3_deciles_capture_pct": pct(top3.is_late.sum() / te.is_late.sum()),
        "top3_deciles_low_review_pct": pct(top3.is_low_review.mean()),
        "top3_deciles_late_rate_pct": pct(top3.is_late.mean()),
        "top3_deciles_orders_per_month": round(len(top3) / 5),
    }

    # ---------------- 8. review comment themes ----------------
    rv = q(con, f"""SELECT order_id, is_late, review_comment_message FROM fct_orders
                    WHERE {WINDOW} AND is_low_review = 1 AND review_comment_message IS NOT NULL""")
    tags = rv.review_comment_message.map(tag)
    rv["delivery_issue"] = tags.map(lambda t: int(bool(t & {"not_received", "late"})))
    rv["product_issue"] = tags.map(lambda t: int(bool(t & {"wrong_or_missing_item", "defective_damaged", "quality_not_as_described"})))
    rv["service_issue"] = tags.map(lambda t: int("refund_cancel_service" in t))
    lab = pd.read_csv(OUT / "review_theme_test_labels.csv")
    lt = lab.review_comment_message.map(tag)
    lab["pred_delivery"] = lt.map(lambda t: int(bool(t & {"not_received", "late"})))
    lab["pred_product"] = lt.map(lambda t: int(bool(t & {"wrong_or_missing_item", "defective_damaged", "quality_not_as_described"})))

    def pr(pred, gold):
        tp = int(((pred == 1) & (gold == 1)).sum())
        return round(tp / max(pred.sum(), 1), 2), round(tp / max(gold.sum(), 1), 2)
    pd_, rd_ = pr(lab.pred_delivery, lab.gold_delivery_issue)
    pp_, rp_ = pr(lab.pred_product, lab.gold_product_issue)
    obs_deliv, obs_prod = rv.delivery_issue.mean(), rv.product_issue.mean()
    F["review_themes"] = {
        "low_review_comments": len(rv),
        "delivery_issue_tagged_pct": pct(obs_deliv), "product_issue_tagged_pct": pct(obs_prod),
        "service_issue_tagged_pct": pct(rv.service_issue.mean()),
        "delivery_issue_bias_corrected_pct": pct(min(obs_deliv * pd_ / rd_, 1)),
        "product_issue_bias_corrected_pct": pct(min(obs_prod * pp_ / rp_, 1)),
        "test_set_n": len(lab),
        "delivery_precision": pd_, "delivery_recall": rd_, "product_precision": pp_, "product_recall": rp_,
        "delivery_issue_share_among_on_time_orders_pct": pct(rv.loc[rv.is_late == 0, "delivery_issue"].mean()),
        "method": "rule-based Portuguese keyword tagging drafted with Claude; tuned on 50-review dev set; "
                  "evaluated on held-out 60-review set labelled manually",
    }

    # ---------------- 9. sizing for recommendations ----------------
    slow_orders_per_yr = d.slow_pay.sum() / 20 * 12
    F["sizing"] = {
        "slow_pay_late_orders_avoidable_per_year": round(slow_orders_per_yr * m2.params["slow_pay"]),
        "slow_pay_low_reviews_avoidable_per_year": round(slow_orders_per_yr * m2.params["slow_pay"] * m1.params["is_late"]),
        "note": "at the platform's 2017-18 volume; assumes adjusted effects are causal (they are observational)",
    }

    (OUT / "findings.json").write_text(json.dumps(F, indent=2, ensure_ascii=False))
    print(json.dumps(F, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
