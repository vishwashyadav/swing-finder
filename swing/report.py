import html
import os

import pandas as pd

CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f5f6f8;color:#1c1e21}
.wrap{max-width:1100px;margin:0 auto;padding:20px}h1{font-size:22px;margin:0 0 4px}.sub{color:#666;font-size:14px}
.pill{display:inline-block;padding:4px 10px;border-radius:999px;font-weight:600;font-size:13px}
.Bullish{background:#d8f3e2;color:#11663a}.Neutral{background:#fff1cc;color:#7a5800}.Bearish{background:#fbdcdc;color:#8a1f1f}
.warn{background:#fff4e5;border-left:4px solid #f0a020;padding:10px 14px;margin:14px 0;border-radius:6px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-top:16px}
.card{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h2{font-size:18px;margin:0;display:flex;justify-content:space-between;align-items:center}
.A{background:#d8f3e2;color:#11663a}.Watch{background:#fff1cc;color:#7a5800}
.setup{color:#555;font-size:13px;margin:4px 0 10px}table.k{width:100%;font-size:14px;border-collapse:collapse}
table.k td{padding:4px 0}table.k td:last-child{text-align:right;font-weight:600}.g{color:#11663a}.r{color:#b42318}
.rules{background:#fff;border-radius:12px;padding:16px;margin-top:18px;font-size:14px;line-height:1.6}
table.t{width:100%;border-collapse:collapse;font-size:13px;background:#fff}table.t th,table.t td{padding:6px 8px;border-bottom:1px solid #eee;text-align:right}
table.t th:first-child,table.t td:first-child{text-align:left}.foot{color:#888;font-size:12px;margin-top:20px}
"""


def _card(t, r):
    name = html.escape(t.replace(".NS", ""))
    tv = f"https://in.tradingview.com/chart/?symbol=NSE:{name}"
    entry_lbl = "Entry (next session, near)" if r["grade"] == "A" else "Buy-stop above"
    return f"""
<div class="card"><h2><a href="{tv}" target="_blank" style="color:inherit;text-decoration:none">{name}</a>
<span class="pill {r['grade']}">{'A-grade' if r['grade']=='A' else 'Watchlist'}</span></h2>
<div class="setup">{html.escape(r['setup'])} · Score {r['score']} · RS {r['rs_pct']:.0f} pct · {r['dist_high']*100:.1f}% below 52w high</div>
<table class="k">
<tr><td>{entry_lbl}</td><td>₹{r['entry']:,.2f}</td></tr>
<tr><td>Stop loss</td><td class="r">₹{r['stop']:,.2f} (−{r['risk_pct']:.1f}%)</td></tr>
<tr><td>Target 1 (book 50%)</td><td class="g">₹{r['target1']:,.2f} (+{r['target1_pct']:.1f}%)</td></tr>
<tr><td>Target 2 / trail 20 EMA</td><td class="g">₹{r['target2']:,.2f}</td></tr>
<tr><td>Quantity</td><td>{int(r['qty'])} sh · ₹{r['invest']:,.0f}</td></tr>
<tr><td>Max loss if SL hits</td><td class="r">₹{r['max_loss']:,.0f}</td></tr>
</table></div>"""


def write_daily(ideas: pd.DataFrame, regime, breadth, asof, cfg, out_dir, n_scanned, history_html=""):
    os.makedirs(out_dir, exist_ok=True)
    warn = ""
    if regime == "Bearish":
        warn = ('<div class="warn"><b>Nifty is below its 200-day average.</b> Swing breakouts fail far more often in this '
                'regime. Position size is set to the "Bearish" multiplier in config (default 0 = watch only).</div>')
    n_a = int((ideas["grade"] == "A").sum()) if not ideas.empty else 0
    if not ideas.empty and n_a < len(ideas):
        warn += (f'<div class="warn">{n_a} stock(s) triggered a full A-grade setup today. The rest are '
                 '<b>watchlist</b> names: strong trend & relative strength, but only buy if price crosses the buy-stop level.</div>')
    cards = "".join(_card(t, r) for t, r in ideas.iterrows()) or "<p>No stocks pass the filters today.</p>"
    ex = cfg["exits"]
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Trade Finder — {asof}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Swing Trade Finder</h1>
<div class="sub">Data as of <b>{asof}</b> · {n_scanned} stocks scanned · Market regime <span class="pill {regime}">{regime}</span>
· Breadth {breadth:.0f}% above 50 DMA</div>
{warn}<div class="grid">{cards}</div>
<div class="rules"><b>Trade rules</b><br>
1. A-grade: buy next session; skip if it opens more than {cfg['strategy']['max_gap_up_pct']}% above the entry price.
Watchlist: place a buy-stop order at the level shown (valid next session only).<br>
2. Place the stop loss immediately after entry. Never move it down.<br>
3. At Target 1 ({ex['target1_r']}R) sell half and move the stop to your entry price.<br>
4. Exit the rest when a day closes below the 20 EMA, or at Target 2.<br>
5. Exit if Target 1 isn't reached within {ex['time_stop_days']} trading days.<br>
6. Quantity risks {cfg['account']['risk_per_trade_pct']}% of ₹{cfg['account']['capital']:,} per trade (edit config.yaml).</div>
{history_html}
<div class="foot">Educational tool, not investment advice. Past performance does not guarantee future returns.
Data: Yahoo Finance (end of day).</div></div></body></html>"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)


def history_table(hist: pd.DataFrame, n=40) -> str:
    if hist is None or hist.empty:
        return ""
    h = hist.tail(n).iloc[::-1]
    rows = "".join(
        f"<tr><td>{r.date}</td><td>{html.escape(str(r.ticker).replace('.NS',''))}</td><td>{r.grade}</td>"
        f"<td>{r.entry:.2f}</td><td>{r.stop:.2f}</td><td>{r.target1:.2f}</td></tr>" for r in h.itertuples())
    return ("<div class='rules'><b>Recent signals</b> (full log in signals_history.csv)<table class='t'>"
            "<tr><th>Date</th><th>Stock</th><th>Grade</th><th>Entry</th><th>SL</th><th>T1</th></tr>"
            f"{rows}</table></div>")
