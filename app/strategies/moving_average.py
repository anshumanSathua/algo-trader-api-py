import pandas as pd
from app.utils.indicators import sma


def moving_average_crossover(df: pd.DataFrame, short_window: int = 20, long_window: int = 50):
    """
    Generate buy/sell signals based on SMA crossover.
    Returns the DataFrame with added columns: short_sma, long_sma, signal.
    """
    df = df.copy()
    df["short_sma"] = sma(df["Close"], short_window)
    df["long_sma"] = sma(df["Close"], long_window)
    df["signal"] = 0
    df.loc[df["short_sma"] > df["long_sma"], "signal"] = 1
    df.loc[df["short_sma"] < df["long_sma"], "signal"] = -1

    df["crossover"] = df["signal"].diff()

    return df
