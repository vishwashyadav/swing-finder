import io
import os
import pickle
import time

import pandas as pd

from . import ROOT

NSE_500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
INDEX_TICKER = "^NSEI"


def load_universe(cfg) -> list:
    """Returns Yahoo tickers like 'RELIANCE.NS'."""
    if cfg["universe"]["source"] == "nifty500":
        try:
            import requests

            r = requests.get(NSE_500_URL, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
            r.raise_for_status()
            syms = pd.read_csv(io.StringIO(r.text))["Symbol"].dropna().astype(str).tolist()
            if len(syms) > 400:
                print(f"Universe: Nifty 500 from NSE ({len(syms)} stocks)")
                return [f"{x.strip()}.NS" for x in syms]
        except Exception as e:  # NSE often blocks cloud servers - fall back silently
            print(f"NSE list unavailable ({e}); using bundled list")
    path = os.path.join(ROOT, "swing", "universe_fallback.txt")
    with open(path) as fh:
        syms = [x.strip() for x in fh if x.strip() and not x.startswith("#")]
    print(f"Universe: bundled list ({len(syms)} stocks)")
    return [f"{x}.NS" for x in syms]


def _clean(df: pd.DataFrame):
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[(df["Close"] > 0) & (df["Volume"] >= 0)]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df if len(df) >= 220 else None


def download(tickers, period="2y", start=None, chunk=80, cache=None) -> dict:
    """Download daily adjusted OHLCV from Yahoo Finance. Returns {ticker: DataFrame}."""
    if cache and os.path.exists(cache):
        age_h = (time.time() - os.path.getmtime(cache)) / 3600
        if age_h < 12:
            with open(cache, "rb") as fh:
                print(f"Using cached data ({cache})")
                return pickle.load(fh)

    import yfinance as yf

    out = {}
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        kw = dict(group_by="ticker", auto_adjust=True, progress=False, threads=True)
        kw.update({"start": start} if start else {"period": period})
        for attempt in range(3):
            try:
                raw = yf.download(part, **kw)
                break
            except Exception as e:
                print(f"download retry {attempt + 1}: {e}")
                time.sleep(5)
        else:
            continue
        for t in part:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = _clean(df)
                if df is not None:
                    out[t] = df
            except KeyError:
                pass
        print(f"  downloaded {min(i + chunk, len(tickers))}/{len(tickers)}")

    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as fh:
            pickle.dump(out, fh)
    return out


def download_index(period="2y", start=None) -> pd.DataFrame:
    import yfinance as yf

    kw = {"start": start} if start else {"period": period}
    df = yf.download(INDEX_TICKER, auto_adjust=True, progress=False, **kw)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.dropna()
