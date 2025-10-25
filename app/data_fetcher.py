import yfinance as yf
import pandas as pd


def fetch_historical_data(symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
    """
    Returns a pandas DataFrame with index=Date and columns:
    Open, High, Low, Close, Volume (Close ensured and numeric).
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=False)

    if df is None or df.empty:
        df = yf.download(symbol, period=period,
                         interval=interval, progress=False)

    if df is None:
        return pd.DataFrame()

    if isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index.name = "Date"

    if "Close" not in df.columns and "Adj Close" in df.columns:
        df["Close"] = df["Adj Close"]

    expected_cols = ["Open", "High", "Low", "Close", "Volume"]
    available = [c for c in expected_cols if c in df.columns]
    df = df[available].copy()

    if "Close" in df.columns:
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")

    return df
