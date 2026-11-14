# Swing Trade Finder (NSE)

Scans Nifty 500 stocks every weekday after market close. You get the day's swing ideas with entry, stop loss, targets and quantity on a web page, and optionally on Telegram. Hosting is free on GitHub (Actions + Pages), so you don't need a server.

## What it does

| Step | Rule |
|---|---|
| Tradable | Price ≥ ₹50, 20-day average traded value ≥ ₹10 cr |
| Trend | Close > 50 SMA > 200 SMA, 200 SMA rising |
| Leader | Top 30% 6-month relative strength vs Nifty, within 25% of the 52-week high |
| Setup | **Breakout**: close above a tight 20-day base on ≥1.5× volume, **or** **Pullback**: dip to the 20 EMA on light volume, then turns up |
| Risk | Stop = tighter of the 10-day swing low and 2×ATR (must be ≤ 8% away). Quantity risks 1% of capital. |
| Exit | Sell half at 2R and move the stop to breakeven. Trail the rest on the 20 EMA. 15-day time stop. |
| Market filter | Full size when Nifty is bullish, half when neutral, watch-only when Nifty is below its 200 DMA |

Every day you get **at least 5 ideas**:
- 🟢 **A-grade**: a full setup triggered today. Buy next session near the entry price.
- 🟡 **Watchlist**: passes trend and strength but hasn't triggered yet. Place a **buy-stop** at the level shown. If price doesn't cross it, no trade.

All settings are in `config.yaml` (capital, risk %, filters).

---

## Deploy for free (about 10 minutes, no coding)

### 1. Put the code on GitHub
1. Create a free account at https://github.com.
2. Click **New repository** and name it `swing-finder`. Choose **Public** (GitHub Pages and unlimited Actions minutes are free for public repos).
3. Click **uploading an existing file** and drag in **all** the files and folders from this zip, including the `.github` folder. Then click **Commit**.
   - If the `.github` folder doesn't upload (hidden folders sometimes don't), create the file manually: **Add file → Create new file**, name it `.github/workflows/daily-scan.yml` and paste in the contents. Do the same for `backtest.yml`.

### 2. Let the bot save reports
**Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → Save.

### 3. Turn on the web page
**Settings → Pages** → Source: **Deploy from a branch** → Branch: `main`, folder `/docs` → Save.
Your page will be at `https://<your-username>.github.io/swing-finder/`.

### 4. (Optional) Telegram alerts on your phone
1. In Telegram, message **@BotFather**, send `/newbot` and follow the steps. Copy the **token**.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `"chat":{"id": ...}` number.
3. In GitHub, go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `TELEGRAM_BOT_TOKEN` = your token
   - `TELEGRAM_CHAT_ID` = your chat id

### 5. Run it
**Actions** tab → **Daily swing scan** → **Run workflow**. After it finishes (about 3–5 minutes), open your page.
From then on it runs automatically at **5:17 PM IST, Monday to Friday**.

### 6. Backtest before you trade (important)
**Actions → Backtest → Run workflow** (takes 10–30 minutes). Then open `https://<your-username>.github.io/swing-finder/backtest.html`.
It shows CAGR, max drawdown, win rate, monthly returns and how many months hit 5%+. Check these numbers before you trade real money.

---

## Run on your own computer (optional)
```bash
pip install -r requirements.txt
python run_daily.py      # today's ideas -> docs/index.html
python backtest.py       # history -> docs/backtest.html
```

## Notes
- A private repo also works, but free GitHub Pages needs a public repo. With a private repo, use Telegram for alerts.
- Data is from Yahoo Finance (end of day, free). An occasional symbol may fail. It's skipped automatically.
- NSE sometimes blocks cloud servers from downloading the Nifty 500 list. The app then uses a bundled list of about 250 liquid stocks (`swing/universe_fallback.txt`).
- GitHub may delay scheduled runs by a few minutes on busy days, and it pauses schedules in repos with no activity for 60 days. The daily commits keep the repo active.

## Honest expectations
- No strategy wins every month. Expect losing months, especially when Nifty is falling. That's why the market filter cuts position size.
- The backtest uses today's stock list, so it can't include companies that were delisted (survivorship bias). Real results are usually somewhat worse.
- Paper trade for 1–2 months and compare with the backtest before going live.
- This is an educational tool, not investment advice. Always place the stop loss.
