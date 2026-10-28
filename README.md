# Late Orders, Lost Stars
**Author:** Cindy Wang · 📄 [Full report (PDF)](outputs/Late_Orders_Lost_Stars_Project_Report.pdf)

### Payments & delivery analytics on 99,092 real marketplace orders (Olist, Brazil, 2017–2018)

**Question:** Which payment and fulfilment problems cost a marketplace its customers' trust, and how would we prove a fix works?

## Key findings
| # | Finding | Evidence |
|---|---|---|
| 1 | A late delivery raises the chance of a 1–2★ review by **51.8 pp** (95% CI 50.5–53.0) | OLS with state, category, value and month fixed effects, robust SE, n = 95,560 |
| 2 | Payments approved after 24h are **29% more likely to arrive late** (+1.86 pp) | Boleto averages 33.1h to approve vs 4.4h for cards; delivery promise starts at purchase |
| 3 | 7+ installment orders are 16.2% of card orders but **34.0% of card GMV** | AOV R$302 vs R$83 for single payments |
| 4 | **92% of payment reconciliation breaks** (228 of 249) are installment interest | payment total vs items + freight, per order |
| 5 | 172 at-risk sellers = 17.4% of orders but **29.4% of late deliveries** | 30+ orders and late or low-review rate ≥ 1.5× platform |
| 6 | Late-risk model: **AUC 0.68 out-of-time**; top decile 2.6× average late rate | trained to Mar 2018, tested Apr–Aug 2018 |
| 7 | Late delivery does **not** significantly change 180-day repurchase (p = 0.23) | reported as a null result |

## Experiment designed (not run)
Proactive delay alerts for the top 30% risk orders. Primary metric: 1–2★ review rate (baseline 11.1%).
MDE −2 pp (18% relative), α 0.05, power 0.8 → **3,567 orders per arm (~16 weeks at 2018 volume)**.
Validated with 2,000 simulations on resampled real orders: A/A false-positive rate 5.4%, power 78.8%.

## How it is built
```
data_raw/ (8 CSVs) → sql/01_staging.sql → sql/02_marts.sql → metrics/metrics.yml → src/analysis.py → outputs/
                         clean, dedupe      fct_orders, dim_*      12 metrics,           model, tests,
                                            (window functions)     compiled to SQL       dashboard.html
```
- **Metric semantic layer** (`metrics/metrics.yml` + `src/semantic_layer.py`): each metric defined once, compiled to SQL, with allowed-dimension validation.
- **14 data-quality checks** (`sql/dq_checks.sql`): blocking checks stop the build; found 814 duplicate review IDs, 775 orders without items, 249 reconciliation breaks.
- **Review text themes** (`src/review_themes.py`): Portuguese keyword rules, tuned on a 50-review dev set, evaluated on 60 hand-labelled held-out reviews (delivery precision 0.79 / recall 0.68).

## Run it
```bash
pip install pandas pyyaml statsmodels scikit-learn
bash scripts/download_data.sh
python src/build_warehouse.py      # load, model, data-quality checks
python src/analysis.py             # findings.json + tables
python src/experiment_design.py    # power analysis + simulations
python src/build_dashboard.py      # outputs/dashboard.html
python src/export_report.py        # outputs/Late_Orders_Lost_Stars_Project_Report.pdf (needs playwright)
```

## AI usage
Claude was used to draft SQL models, pipeline code and keyword rules, and to debug. All numbers are produced by the scripts above; keyword rules were evaluated on a held-out labelled sample before use.

## Limits
Observational effects (hence the experiment); one Brazilian marketplace, 2017–18; small labelled sample for text themes.

## Sources
1. Olist. *Brazilian E-Commerce Public Dataset by Olist*. Kaggle, 2018. CC BY-NC-SA 4.0. https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
2. bulutttt. *olist-raw-data* (byte-identical mirror of 1). Hugging Face. https://huggingface.co/datasets/bulutttt/olist-raw-data
3. Payments Canada. *Canadian Payment Methods and Trends Report 2025* (12th ed.), PDF pp. 7, 16, 18. https://www.payments.ca/sites/default/files/PaymentsCanada_Canadian_Payment_Methods_and_Trends_2025_EN.pdf
4. Payments Canada. "Canada reaches $12.2 trillion in payment transactions in 2024." https://www.payments.ca/insights/research/canada-reaches-122-trillion-payment-transactions-2024-credit-cards-accounting-1-3
5. Seabold & Perktold. statsmodels. Proc. SciPy, 2010.
6. Pedregosa et al. Scikit-learn: Machine Learning in Python. JMLR 12, 2011.
7. McKinney. Data Structures for Statistical Computing in Python (pandas). Proc. SciPy, 2010.
