import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import base64
import pandas as pd


def plot_strategy(df, symbol: str, strategy_name: str):
    """
    Generates PNG chart with:
     - Top: price + buy/sell markers
     - Middle: RSI (if present)
     - Bottom: Equity curve (if PortfolioValue present in df)
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])

    try:
        conn = sqlite3.connect("data/trades.db", check_same_thread=False)
        c = conn.cursor()
        c.execute(
            "SELECT dt, total_value FROM portfolio_snapshot WHERE symbol=? ORDER BY id",
            (symbol.upper(),),
        )
        rows = c.fetchall()
        conn.close()
        if rows:
            snap_df = pd.DataFrame(
                rows, columns=["Date", "PortfolioValue"])
            snap_df["Date"] = pd.to_datetime(snap_df["Date"])
            merged = pd.merge(df, snap_df, on="Date", how="left")
            merged["PortfolioValue"] = merged["PortfolioValue"].ffill().bfill()
            df = merged
    except Exception as e:
        print("⚠️ Warning: could not attach portfolio snapshots:", e)
        pass

    has_rsi = "RSI" in df.columns
    has_equity = "PortfolioValue" in df.columns

    nrows = 1 + (1 if has_rsi else 0) + (1 if has_equity else 0)
    fig, axes = plt.subplots(nrows=nrows, ncols=1,
                             figsize=(11, 4 * nrows), sharex=True)

    if nrows == 1:
        price_ax = axes
        rsi_ax = None
        equity_ax = None
    else:
        axes = list(axes)
        price_ax = axes[0]
        if has_rsi:
            rsi_ax = axes[1]
            equity_ax = axes[2] if has_equity else (
                axes[2] if nrows == 3 else None)
        else:
            rsi_ax = None
            equity_ax = axes[1] if has_equity else None

    price_ax.plot(df["Date"], df["Close"], label="Close",
                  color="blue", linewidth=1.5)
    buys = df[df["signal"] == 1]
    sells = df[df["signal"] == -1]
    if not buys.empty:
        price_ax.scatter(buys["Date"], buys["Close"], marker="^",
                         color="green", label="BUY", s=60, zorder=5)
    if not sells.empty:
        price_ax.scatter(sells["Date"], sells["Close"], marker="v",
                         color="red", label="SELL", s=60, zorder=5)
    price_ax.set_title(f"{symbol} - {strategy_name} Strategy")
    price_ax.set_ylabel("Price")
    price_ax.legend()

    if has_rsi and rsi_ax is not None:
        rsi_ax.plot(df["Date"], df["RSI"], color="purple", linewidth=1.2)
        rsi_ax.axhline(30, color="green", linestyle="--", linewidth=0.8)
        rsi_ax.axhline(70, color="red", linestyle="--", linewidth=0.8)
        rsi_ax.set_ylabel("RSI")
        rsi_ax.legend()

    if has_equity and equity_ax is not None:
        equity_ax.plot(df["Date"], df["PortfolioValue"],
                       color="tab:orange", linewidth=1.5, label="Portfolio Value")
        equity_ax.set_ylabel("Portfolio Value")
        equity_ax.legend()

    price_ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    price_ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=45)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    return encoded
