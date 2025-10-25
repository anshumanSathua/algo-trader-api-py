import pandas as pd


def backtest_strategy(df: pd.DataFrame, initial_balance: float = 10000.0):
    """
    Simple backtesting engine.
    df must contain columns: Date, Close, signal
    """
    df = df.copy().reset_index(drop=True)
    balance = initial_balance
    position = 0
    portfolio_values = []
    trades = []

    for i in range(len(df)):
        price = df.loc[i, "Close"]
        signal = df.loc[i, "signal"]

        if signal == 1 and position == 0:
            position = balance / price
            balance = 0
            trades.append({
                "Date": str(df.loc[i, "Date"]),
                "Action": "BUY",
                "Price": float(price)
            })

        elif signal == -1 and position > 0:
            balance = position * price
            position = 0
            trades.append({
                "Date": str(df.loc[i, "Date"]),
                "Action": "SELL",
                "Price": float(price)
            })

        total_value = balance + (position * price)
        portfolio_values.append(total_value)

    df["PortfolioValue"] = portfolio_values
    df["PnL"] = df["PortfolioValue"] - initial_balance
    df["Date"] = df["Date"].astype(str)

    final_balance = balance + (position * df["Close"].iloc[-1])
    total_return = ((final_balance - initial_balance) / initial_balance) * 100

    results = {
        "initial_balance": float(initial_balance),
        "final_balance": round(float(final_balance), 2),
        "total_return_pct": round(float(total_return), 2),
        "trades": trades,
        "equity_curve": df[["Date", "PortfolioValue", "PnL"]]
        .astype({"PortfolioValue": float, "PnL": float})
        .to_dict(orient="records")
    }

    return results
