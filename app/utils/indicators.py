import pandas as pd
import numpy as np


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=1).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """
    Robust RSI implementation that handles non-numeric and short series.
    Returns a Series with RSI values (0-100). NaNs replaced with None for JSON friendliness.
    """
    series = pd.to_numeric(series, errors="coerce").astype(float).copy()

    if series.dropna().empty or window < 1:
        return pd.Series([None] * len(series), index=series.index)

    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -1.0 * delta.clip(upper=0.0)

    ma_up = up.ewm(alpha=1.0 / window, adjust=False, min_periods=0).mean()
    ma_down = down.ewm(alpha=1.0 / window, adjust=False, min_periods=0).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ma_up / ma_down.replace(0, np.nan)
        rsi_series = 100.0 - (100.0 / (1.0 + rs))

    return rsi_series.where(rsi_series.notna(), None)
