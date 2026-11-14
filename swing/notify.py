import os


def send_telegram(text: str) -> bool:
    """Sends a message if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars are set."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not configured - skipping")
        return False
    import requests

    for i in range(0, len(text), 3900):  # Telegram limit is 4096 chars
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text[i:i + 3900], "parse_mode": "HTML",
                                "disable_web_page_preview": "true"}, timeout=20)
        if not r.ok:
            print(f"Telegram error: {r.text}")
            return False
    print("Telegram message sent")
    return True


def telegram_text(ideas, regime, breadth, asof, page_url=None) -> str:
    lines = [f"<b>📈 Swing ideas — {asof}</b>",
             f"Market: <b>{regime}</b> | Breadth {breadth:.0f}% above 50 DMA", ""]
    if regime == "Bearish":
        lines += ["⚠️ Nifty below 200 DMA: watch only, no fresh buys recommended.", ""]
    for t, r in ideas.iterrows():
        tag = "🟢 A" if r["grade"] == "A" else "🟡 Watch"
        lines.append(
            f"{tag} <b>{t.replace('.NS', '')}</b> — {r['setup']}\n"
            f"   Entry ₹{r['entry']:.2f} | SL ₹{r['stop']:.2f} (-{r['risk_pct']:.1f}%)\n"
            f"   T1 ₹{r['target1']:.2f} (+{r['target1_pct']:.1f}%) | T2 ₹{r['target2']:.2f}\n"
            f"   Qty {r['qty']} (₹{r['invest']:,.0f}) | Score {r['score']}")
    if ideas.empty:
        lines.append("No stocks pass the filters today.")
    if page_url:
        lines += ["", f"Full report: {page_url}"]
    lines += ["", "<i>Not investment advice. Always use the stop loss.</i>"]
    return "\n".join(lines)
