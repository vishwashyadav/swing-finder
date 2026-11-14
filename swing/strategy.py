"""
Strategy: "Trend + Relative Strength + Setup"
------------------------------------------------
1. Tradable:   price >= min_price, 20d avg traded value >= min crore
2. Trend:      Close > 50 SMA > 200 SMA, 200 SMA rising
3. Leader:     within 25% of 52-week high, top 30% relative strength vs Nifty (6m)
4. Setup (either):
     Breakout  - close above a tight 20-day base on >= 1.5x volume
     Pullback  - dip to 20 EMA in an uptrend on light volume, then turns up
5. Risk:       stop = tighter of 10-day swing low / 2 ATR, must be <= 8% away
6. Regime:     position size scaled by Nifty trend (Bullish / Neutral / Bearish)

The SAME function (compute_features) is used for the daily scan and the backtest,
so what you backtest is exactly what you trade.
"""
import numpy as np
import pandas as pd

from .indicators import atr, ema, rsi, sma


def compute_features(df: pd.DataFrame, idx_close: pd.Series, cfg: dict) -> pd.DataFrame:
    s, u = cfg["strategy"], cfg["universe"]
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

    f = pd.DataFrame(index=df.index)
    f["open"], f["high"], f["low"], f["close"], f["volume"] = df["Open"], h, l, c, v
    f["ema20"] = ema(c, 20)
    f["sma50"] = sma(c, 50)
    f["sma200"] = sma(c, 200)
    f["rsi"] = rsi(c, 14)
    f["atr"] = atr(df, 14)
    f["vol20"] = v.rolling(20).mean()
    f["tv20_cr"] = (c * v).rolling(20).mean() / 1e7
    f["hi252"] = h.rolling(252, min_periods=150).max()
    f["base_hi"] = h.shift(1).rolling(s["base_len"]).max()
    f["base_lo"] = l.shift(1).rolling(s["base_len"]).min()
    f["base_depth"] = (f["base_hi"] - f["base_lo"]) / f["base_hi"]
    f["swing_lo"] = l.rolling(10).min()

    idx = idx_close.reindex(df.index).ffill()
    f["rs_raw"] = (c / c.shift(126)) / (idx / idx.shift(126))
    f["ret_6m"] = c / c.shift(126) - 1
    f["dist_high"] = 1 - c / f["hi252"]
    f["vol_ratio"] = v / f["vol20"]

    f["liquid"] = (c >= u["min_price"]) & (f["tv20_cr"] >= u["min_avg_traded_value_cr"])
    f["trend"] = (c > f["sma50"]) & (f["sma50"] > f["sma200"]) & (f["sma200"] > f["sma200"].shift(20))
    f["near_high"] = f["dist_high"] <= s["max_dist_from_high"]

    rng = (h - l).replace(0, np.nan)
    close_pos = (c - l) / rng
    day_ret = c / c.shift(1) - 1
    breakout = (
        (c > f["base_hi"])
        & (f["vol_ratio"] >= s["breakout_vol_mult"])
        & (f["base_depth"] <= s["max_base_depth"])
        & (close_pos >= 0.5)
        & (day_ret <= 0.08)  # don't chase a stock that already ran 8%+ today
    )
    touched_ema = l.rolling(3).min() <= f["ema20"] * 1.015
    pullback = (
        touched_ema
        & (c > f["ema20"])
        & (c > h.shift(1))
        & f["rsi"].between(40, 65)
        & (f["rsi"] > f["rsi"].shift(1))
        & (v.rolling(5).mean().shift(1) < f["vol20"])
    )
    f["setup"] = np.where(breakout, "Breakout", np.where(pullback, "Pullback", ""))

    stop = np.maximum(f["swing_lo"], c - 2 * f["atr"])
    stop = np.minimum(stop, c - 0.75 * f["atr"])  # never tighter than 0.75 ATR
    f["stop"] = stop
    f["risk_pct"] = (c - stop) / c * 100
    return f


def score(rs_pct, dist_high, risk_pct, vol_ratio, setup, max_stop):
    """0-100 ranking score. Higher = stronger candidate."""
    rs_pct = np.nan_to_num(np.asarray(rs_pct, dtype=float))
    near = np.clip(1 - np.asarray(dist_high, dtype=float) / 0.25, 0, 1)
    risk = np.clip(1 - np.asarray(risk_pct, dtype=float) / max_stop, 0, 1)
    vol = np.clip(np.asarray(vol_ratio, dtype=float) / 2.5, 0, 1)
    vol = np.where(np.asarray(setup) == "Pullback", 0.6, vol)  # pullbacks are meant to be quiet
    return np.round(0.45 * rs_pct + 25 * near + 15 * risk + 15 * np.nan_to_num(vol), 1)


def regime_series(idx_close: pd.Series) -> pd.Series:
    s50, s200 = sma(idx_close, 50), sma(idx_close, 200)
    reg = pd.Series("Neutral", index=idx_close.index)
    reg[(idx_close > s200) & (s50 > s200)] = "Bullish"
    reg[idx_close < s200] = "Bearish"
    return reg


def build_ideas(last: pd.DataFrame, regime: str, cfg: dict) -> pd.DataFrame:
    """last: one row per ticker (latest bar) with feature columns + rs_pct."""
    s, a, ex = cfg["strategy"], cfg["account"], cfg["exits"]
    mult = float(cfg["regime"].get(regime, 0.5))

    base = last[last["liquid"] & last["trend"] & last["near_high"] & (last["rs_pct"] >= 100 - s["rs_top_pct"])].copy()
    if base.empty:
        return base

    is_a = (base["setup"] != "") & base["risk_pct"].between(1, s["max_stop_pct"])
    base["grade"] = np.where(is_a, "A", "Watch")

    # A-grade: buy next session near today's close. Watch: buy-stop just above today's high.
    base["entry"] = np.where(is_a, base["close"], base["high"] * 1.002)
    stop = np.maximum(base["swing_lo"], base["entry"] - 2 * base["atr"])
    stop = np.minimum(stop, base["entry"] - 0.75 * base["atr"])
    base["stop"] = stop
    base["risk_pct"] = (base["entry"] - base["stop"]) / base["entry"] * 100
    base = base[base["risk_pct"].between(1, s["max_stop_pct"])].copy()
    if base.empty:
        return base

    r = base["entry"] - base["stop"]
    base["target1"] = base["entry"] + ex["target1_r"] * r
    base["target2"] = base["entry"] + ex["target2_r"] * r
    base["target1_pct"] = (base["target1"] / base["entry"] - 1) * 100

    risk_amt = a["capital"] * a["risk_per_trade_pct"] / 100 * mult
    qty_risk = np.floor(risk_amt / r)
    qty_cap = np.floor(a["capital"] * a["max_position_pct"] / 100 / base["entry"])
    base["qty"] = np.minimum(qty_risk, qty_cap).astype(int)
    if mult > 0:  # drop stocks too expensive for even 1 share at this capital
        base = base[base["qty"] >= 1].copy()
    base["invest"] = base["qty"] * base["entry"]
    base["max_loss"] = base["qty"] * r

    base["score"] = score(base["rs_pct"], base["dist_high"], base["risk_pct"],
                          base["vol_ratio"], base["setup"], s["max_stop_pct"])
    base["setup"] = base["setup"].replace("", "Near-breakout (buy-stop)")
    base = base.sort_values(["grade", "score"], ascending=[True, False])

    rep = cfg["report"]
    n_a = int((base["grade"] == "A").sum())
    n = min(max(rep["min_ideas"], n_a), rep["max_ideas"])
    return base.head(n)
