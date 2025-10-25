import pandas as pd
from app.utils.indicators import rsi


def rsi_momentum_strategy(df: pd.DataFrame, lower: int = 30, upper: int = 70, window: int = 14):
    df = df.copy()
    df["RSI"] = rsi(df["Close"], window)
    df["signal"] = 0

    min_rsi, max_rsi = df["RSI"].min(), df["RSI"].max()
    if (max_rsi - min_rsi) < 20:
        lower = int(min_rsi + (max_rsi - min_rsi) * 0.3)
        upper = int(min_rsi + (max_rsi - min_rsi) * 0.7)

    df.loc[df["RSI"] < lower, "signal"] = 1
    df.loc[df["RSI"] > upper, "signal"] = -1

    return df
