"""
Render the 9-page print report (outputs/*.pdf) from the same outputs/ data as the dashboard.
Author details live in report_author.json at the project root.

Usage:  python src/export_report.py
"""
from pathlib import Path
import asyncio
import json
import sys

import pandas as pd
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def records(name):
    return json.loads(pd.read_csv(OUT / f"{name}.csv").to_json(orient="records"))


def seller_comparison() -> list:
    sc = pd.read_csv(OUT / "seller_scorecard.csv")
    g = sc.groupby("at_risk").agg(sellers=("seller_id", "size"), median_orders=("orders", "median"),
                                  late_rate=("late_rate", "mean"), low_review_rate=("low_review_rate", "mean"),
                                  avg_review=("avg_review", "mean"), gmv=("gmv", "sum")).reset_index()
    g["group"] = g.at_risk.map({True: "At-risk sellers", False: "Other sellers (30+ orders)"})
    return json.loads(g.sort_values("at_risk", ascending=False).to_json(orient="records"))


def build_html() -> str:
    data = {
        "f": json.loads((OUT / "findings.json").read_text()),
        "exp": json.loads((OUT / "experiment_design.json").read_text()),
        "monthly": records("monthly_metrics"), "late": records("late_buckets"), "pay": records("payment_methods"),
        "lag": records("approval_lag_late"), "inst": records("installments"), "dec": records("risk_deciles"),
        "power": records("power_curve"), "dq": records("dq_report"),
        "seller_cmp": seller_comparison(),
    }
    author = json.loads((ROOT / "report_author.json").read_text())
    tpl = (ROOT / "src" / "report_template.html").read_text()
    return (tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
               .replace("/*__AUTHOR__*/null", json.dumps(author, ensure_ascii=False)))


async def render(html: str, pdf_path: Path) -> list:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 900, "height": 1200})
        await page.set_content(html)
        await page.wait_for_timeout(2500)          # web fonts
        overflow = await page.evaluate("""[...document.querySelectorAll('.page')].map((p, i) => {
            const foot = p.querySelector('.foot, .src');
            const limit = foot ? foot.offsetTop : p.clientHeight;
            const kids = [...p.children].filter(k => k !== foot);
            const bottom = Math.max(...kids.map(k => k.offsetTop + k.offsetHeight));
            return {page: i + 1, spare_px: Math.round(limit - bottom)};
        })""")
        await page.emulate_media(media="print")
        await page.pdf(path=str(pdf_path), width="8.5in", height="11in", print_background=True,
                       margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        await browser.close()
        return overflow


def main():
    pdf = OUT / "Late_Orders_Lost_Stars_Project_Report.pdf"
    fit = asyncio.run(render(build_html(), pdf))
    for f in fit:
        flag = "OVERFLOW" if f["spare_px"] < 8 else "ok"
        print(f"page {f['page']}: {f['spare_px']:>4}px spare  {flag}")
    print(f"wrote {pdf}")
    if any(f["spare_px"] < 8 for f in fit):
        sys.exit(1)


if __name__ == "__main__":
    main()
