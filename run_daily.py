"""Daily scan: run after market close (GitHub Actions does this automatically at 5:15 PM IST)."""
import os

import pandas as pd

from swing import ROOT, load_config
from swing.data import download, download_index, load_universe
from swing.notify import send_telegram, telegram_text
from swing.report import history_table, write_daily
from swing.strategy import build_ideas, compute_features, regime_series

DOCS = os.path.join(ROOT, "docs")


def scan(data: dict, idx: pd.DataFrame, cfg: dict):
    idx_close = idx["Close"]
    rows = {}
    for t, df in data.items():
        f = compute_features(df, idx_close, cfg)
        if len(f) and f.index[-1] >= idx.index[-1] - pd.Timedelta(days=5):  # skip stale/suspended
            rows[t] = f.iloc[-1]
    last = pd.DataFrame(rows).T
    num_cols = [c for c in last.columns if c not in ("setup", "liquid", "trend", "near_high")]
    last[num_cols] = last[num_cols].apply(pd.to_numeric, errors="coerce")
    for c in ("liquid", "trend", "near_high"):
        last[c] = last[c].astype(bool)

    liquid = last[last["liquid"]]
    last["rs_pct"] = liquid["rs_raw"].rank(pct=True) * 100
    last["rs_pct"] = last["rs_pct"].fillna(0)
    breadth = float((liquid["close"] > liquid["sma50"]).mean() * 100) if len(liquid) else 0.0
    regime = regime_series(idx_close).iloc[-1]
    ideas = build_ideas(last, regime, cfg)
    return ideas, regime, breadth, len(last)


def main():
    cfg = load_config()
    tickers = load_universe(cfg)
    idx = download_index(period="2y")
    data = download(tickers, period="2y")
    print(f"Got data for {len(data)} stocks")
    ideas, regime, breadth, n = scan(data, idx, cfg)
    asof = idx.index[-1].strftime("%d %b %Y")

    os.makedirs(DOCS, exist_ok=True)
    cols = ["grade", "setup", "entry", "stop", "risk_pct", "target1", "target1_pct", "target2", "qty", "invest",
            "max_loss", "score", "rs_pct", "dist_high"]
    out = ideas[cols].round(2) if not ideas.empty else pd.DataFrame(columns=cols)
    out.index.name = "ticker"
    out.to_csv(os.path.join(DOCS, "signals.csv"))

    hist_path = os.path.join(DOCS, "signals_history.csv")
    hist = pd.read_csv(hist_path) if os.path.exists(hist_path) else pd.DataFrame()
    if not out.empty:
        new = out.reset_index().assign(date=idx.index[-1].strftime("%Y-%m-%d"), regime=regime)
        if not hist.empty:
            hist = hist[hist["date"] != new["date"].iloc[0]]  # re-runs on same day replace, not duplicate
        hist = pd.concat([hist, new], ignore_index=True)
        hist.to_csv(hist_path, index=False)

    write_daily(ideas, regime, breadth, asof, cfg, DOCS, n, history_table(hist))
    print(f"\nRegime: {regime} | Breadth: {breadth:.0f}% | Ideas: {len(ideas)}")
    print(out[["grade", "setup", "entry", "stop", "target1", "qty"]].to_string() if not out.empty else "none")

    send_telegram(telegram_text(ideas, regime, breadth, asof, os.getenv("PAGE_URL")))


if __name__ == "__main__":
    main()
