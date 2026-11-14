"""
Backtest the exact daily-scan rules on history.

    python backtest.py                     # 2015 -> today
    python backtest.py --start 2018-01-01

Writes docs/backtest.html, docs/backtest_trades.csv, docs/backtest_equity.csv
"""
import argparse
import math
import os

import numpy as np
import pandas as pd

from swing import ROOT, load_config
from swing.data import download, download_index, load_universe
from swing.strategy import compute_features, regime_series, score

DOCS = os.path.join(ROOT, "docs")


def run_backtest(data: dict, idx: pd.DataFrame, cfg: dict, start: str, end: str = None):
    a, s, ex = cfg["account"], cfg["strategy"], cfg["exits"]
    cost = cfg["costs"]["per_side_pct"] / 100
    idx_close = idx["Close"]
    feats = {t: compute_features(df, idx_close, cfg) for t, df in data.items()}
    tickers = list(feats)
    dates = idx.index[(idx.index >= pd.Timestamp(start)) & (idx.index <= pd.Timestamp(end or idx.index[-1]))]

    def panel(col, dtype=float):
        return pd.DataFrame({t: feats[t][col] for t in tickers}).reindex(dates)

    O, H, L, C, E20 = (panel(c).values for c in ("open", "high", "low", "close", "ema20"))
    liquid = panel("liquid").fillna(False).astype(bool)
    base_ok = liquid & panel("trend").fillna(False).astype(bool) & panel("near_high").fillna(False).astype(bool)
    rs_pct = (panel("rs_raw").where(liquid).rank(axis=1, pct=True) * 100).fillna(0)
    setup = panel("setup").fillna("")
    risk = panel("risk_pct")
    sig = (base_ok & (rs_pct >= 100 - s["rs_top_pct"]) & (setup != "") & (risk >= 1) & (risk <= s["max_stop_pct"])).values
    SC = score(rs_pct.values, panel("dist_high").values, risk.values, panel("vol_ratio").values,
               setup.values, s["max_stop_pct"])
    STOP = panel("stop").values
    regime = regime_series(idx_close).reindex(dates).values
    rmult = cfg["regime"]

    cash, pos, pending, trades, curve = float(a["capital"]), {}, [], [], []
    max_pos = a["max_open_positions"]

    def close_out(j, px, qty, d, reason):
        nonlocal cash
        p = pos[j]
        cash += qty * px * (1 - cost)
        p["proceeds"] += qty * px * (1 - cost)
        p["qty"] -= qty
        if p["qty"] == 0:
            pnl = p["proceeds"] - p["cost_basis"]
            trades.append(dict(ticker=tickers[j], entry_date=p["date"].date(), exit_date=d.date(),
                               entry=round(p["entry"], 2), exit=round(px, 2), qty=p["init_qty"],
                               pnl=round(pnl, 0), r_multiple=round(pnl / (p["init_qty"] * p["r"]), 2),
                               days=p["bars"], setup=p["setup"], reason=reason))
            del pos[j]

    for i, d in enumerate(dates):
        eq = curve[-1] if curve else cash
        # 1) fill yesterday's signals at today's open
        for j, sclose, stp, mult, stype in pending:
            o = O[i, j]
            if j in pos or np.isnan(o) or o > sclose * (1 + s["max_gap_up_pct"] / 100) or o <= stp:
                continue
            r = o - stp
            qty = min(math.floor(eq * a["risk_per_trade_pct"] / 100 * mult / r),
                      math.floor(eq * a["max_position_pct"] / 100 / o),
                      math.floor(cash / (o * (1 + cost))))
            if qty <= 0:
                continue
            cash -= qty * o * (1 + cost)
            pos[j] = dict(qty=qty, init_qty=qty, entry=o, stop=stp, r=r, t1=o + ex["target1_r"] * r,
                          t2=o + ex["target2_r"] * r, partial=False, bars=0, flag=None, date=d, setup=stype,
                          cost_basis=qty * o * (1 + cost), proceeds=0.0, last=o)
        pending = []

        # 2) manage open positions
        for j in list(pos):
            p = pos[j]
            o, h, l, c = O[i, j], H[i, j], L[i, j], C[i, j]
            if np.isnan(o):
                continue
            if p["flag"]:
                close_out(j, o, p["qty"], d, p["flag"]); continue
            if o <= p["stop"]:
                close_out(j, o, p["qty"], d, "stop (gap)"); continue
            if l <= p["stop"]:
                close_out(j, p["stop"], p["qty"], d, "breakeven" if p["partial"] else "stop"); continue
            if not p["partial"] and h >= p["t1"]:
                q = p["qty"] // 2
                if q > 0:
                    close_out(j, max(o, p["t1"]), q, d, "t1")
                p["partial"], p["stop"] = True, max(p["stop"], p["entry"])
            if p["partial"] and h >= p["t2"] and j in pos:
                close_out(j, max(o, p["t2"]), p["qty"], d, "t2"); continue
            p["bars"] += 1
            p["last"] = c
            if p["partial"] and c < E20[i, j]:
                p["flag"] = "trail 20 EMA"
            elif not p["partial"] and p["bars"] >= ex["time_stop_days"]:
                p["flag"] = "time stop"
            elif p["bars"] >= ex["max_hold_days"]:
                p["flag"] = "max hold"

        # 3) today's signals -> orders for tomorrow
        mult = float(rmult.get(regime[i], 0.5))
        slots = max_pos - len(pos)
        if mult > 0 and slots > 0:
            cand = [j for j in np.where(sig[i])[0] if j not in pos]
            cand.sort(key=lambda j: -SC[i, j])
            pending = [(j, C[i, j], STOP[i, j], mult, setup.iat[i, j]) for j in cand[:slots]]

        # 4) mark to market
        mtm = sum(p["qty"] * (C[i, j] if not np.isnan(C[i, j]) else p["last"]) for j, p in pos.items())
        curve.append(cash + mtm)

    for j in list(pos):
        close_out(j, pos[j]["last"], pos[j]["qty"], dates[-1], "end of test")

    equity = pd.Series(curve, index=dates, name="equity")
    return equity, pd.DataFrame(trades)


def metrics(equity: pd.Series, trades: pd.DataFrame, idx_close: pd.Series) -> dict:
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    dd = (equity / equity.cummax() - 1).min()
    b = idx_close.reindex(equity.index).ffill()
    bench = (b.iloc[-1] / b.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    try:
        monthly = equity.resample("ME").last().pct_change().dropna()
    except ValueError:
        monthly = equity.resample("M").last().pct_change().dropna()
    m = dict(start=str(equity.index[0].date()), end=str(equity.index[-1].date()),
             final_equity=round(equity.iloc[-1]), cagr_pct=round(cagr * 100, 1), nifty_cagr_pct=round(bench * 100, 1),
             max_drawdown_pct=round(dd * 100, 1), avg_month_pct=round(monthly.mean() * 100, 2),
             months_ge_5pct=f"{(monthly >= 0.05).mean() * 100:.0f}%", losing_months=f"{(monthly < 0).mean() * 100:.0f}%",
             trades=len(trades))
    if len(trades):
        w, lo = trades[trades.pnl > 0], trades[trades.pnl <= 0]
        m.update(win_rate_pct=round(len(w) / len(trades) * 100, 1),
                 avg_win_r=round(w.r_multiple.mean(), 2) if len(w) else 0,
                 avg_loss_r=round(lo.r_multiple.mean(), 2) if len(lo) else 0,
                 expectancy_r=round(trades.r_multiple.mean(), 2),
                 profit_factor=round(w.pnl.sum() / abs(lo.pnl.sum()), 2) if lo.pnl.sum() else float("inf"),
                 avg_days_held=round(trades.days.mean(), 1),
                 trades_per_month=round(len(trades) / max(len(monthly), 1), 1))
    return m, monthly


def write_report(m, monthly, equity, trades, out_dir, cost_pct=0.15):
    os.makedirs(out_dir, exist_ok=True)
    equity.to_csv(os.path.join(out_dir, "backtest_equity.csv"))
    trades.to_csv(os.path.join(out_dir, "backtest_trades.csv"), index=False)

    e = equity.values
    xs = np.linspace(0, 1000, len(e))
    ys = 280 - (e - e.min()) / (e.max() - e.min() + 1e-9) * 260
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    labels = {"cagr_pct": "CAGR %", "nifty_cagr_pct": "Nifty CAGR %", "max_drawdown_pct": "Max drawdown %",
              "avg_month_pct": "Avg month %", "months_ge_5pct": "Months ≥ 5%", "losing_months": "Losing months",
              "win_rate_pct": "Win rate %", "expectancy_r": "Expectancy (R/trade)", "profit_factor": "Profit factor",
              "avg_win_r": "Avg win (R)", "avg_loss_r": "Avg loss (R)", "trades": "Trades",
              "trades_per_month": "Trades / month", "avg_days_held": "Avg days held", "final_equity": "Final equity ₹"}
    tiles = "".join(f"<div class='t'><div class='l'>{labels[k]}</div><div class='v'>{m[k]}</div></div>"
                    for k in labels if k in m)
    mt = monthly.to_frame("r")
    mt["y"], mt["m"] = mt.index.year, mt.index.month
    pv = mt.pivot(index="y", columns="m", values="r") * 100
    cells = ""
    for y, row in pv.iterrows():
        tds = "".join(
            "<td></td>" if pd.isna(v) else
            f"<td style='background:{'#d8f3e2' if v >= 5 else '#eef8f1' if v >= 0 else '#fbdcdc'}'>{v:.1f}</td>"
            for v in row.reindex(range(1, 13)))
        cells += f"<tr><th>{y}</th>{tds}</tr>"
    months = "".join(f"<th>{x}</th>" for x in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest</title><style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f5f6f8;margin:0}}
.w{{max-width:1100px;margin:auto;padding:20px}}.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
.t{{background:#fff;border-radius:10px;padding:12px}}.l{{font-size:12px;color:#666}}.v{{font-size:20px;font-weight:700}}
svg,table{{background:#fff;border-radius:10px;margin-top:16px;width:100%}}table{{border-collapse:collapse;font-size:12px}}
td,th{{padding:5px;text-align:center;border-bottom:1px solid #eee}}.n{{font-size:13px;color:#555;line-height:1.6}}</style></head>
<body><div class="w"><h2>Backtest {m['start']} → {m['end']}</h2><div class="g">{tiles}</div>
<svg viewBox="0 0 1000 300" preserveAspectRatio="none" height="300"><polyline fill="none" stroke="#2563eb" stroke-width="2" points="{pts}"/></svg>
<table><tr><th>Year</th>{months}</tr>{cells}</table>
<p class="n"><b>Read this before trusting the numbers:</b> the stock list is today's index members, so companies that were
delisted or dropped out are missing (survivorship bias); real results are usually worse than a backtest. Costs of
{cost_pct}% per side are included. Trade log: backtest_trades.csv.</p></div></body></html>"""
    with open(os.path.join(out_dir, "backtest.html"), "w", encoding="utf-8") as fh:
        fh.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    cfg = load_config()
    dl_start = str(pd.Timestamp(args.start) - pd.Timedelta(days=420))  # warm-up for 200 DMA / 52w high
    idx = download_index(start=dl_start)
    data = download(load_universe(cfg), start=dl_start, cache=os.path.join(ROOT, "data", "cache.pkl"))
    print(f"Backtesting {len(data)} stocks...")
    equity, trades = run_backtest(data, idx, cfg, args.start, args.end)
    m, monthly = metrics(equity, trades, idx["Close"])
    write_report(m, monthly, equity, trades, DOCS, cfg["costs"]["per_side_pct"])
    for k, v in m.items():
        print(f"{k:>18}: {v}")
    print("\nReport: docs/backtest.html")


if __name__ == "__main__":
    main()
