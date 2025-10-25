from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from app.data_fetcher import fetch_historical_data
from app.utils.indicators import sma, rsi
from app.strategies.moving_average import moving_average_crossover
from app.backtest import backtest_strategy
from app.strategies.rsi_strategy import rsi_momentum_strategy
from app.utils.plotter import plot_strategy
import asyncio
from app.live_feed import ws_manager, start_stream_background, stop_stream, stream_status
from app.paper_trader import (
    stop_paper_trader,
    DB_PATH,
    ensure_db,
    run_live_trader,
    trader_state)
import sqlite3
import os
import pandas as pd
import numpy as np
import math
import logging


logger = logging.getLogger("uvicorn")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

app = FastAPI(title="Algo Trader Backend")


@app.get("/ping")
async def ping():
    return {"message": "pong"}


@app.get("/data/{symbol}")
async def get_data(
    symbol: str,
    period: str = Query(
        "1mo", description="yfinance period e.g., 1mo, 3mo, 1y"),
    interval: str = Query(
        "1d", description="yfinance interval e.g., 1d, 1h, 1m"),
    save_csv: bool = Query(
        False, description="If true, save CSV and return file")
):
    """
    Fetch historical OHLCV for a symbol.
    """
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if df.empty:
        raise HTTPException(
            status_code=404, detail="No data found for symbol/params.")

    if save_csv:
        os.makedirs("data", exist_ok=True)
        filename = f"data/{symbol.upper()}_{period}_{interval}.csv"
        df.to_csv(filename)
        return FileResponse(filename, media_type="text/csv", filename=os.path.basename(filename))

    df = df.reset_index()
    df['Date'] = df['Date'].astype(str)
    return JSONResponse(content=df.to_dict(orient="records"))


@app.get("/indicator/{symbol}/sma")
async def get_sma(
    symbol: str,
    window: int = Query(20, description="SMA window"),
    period: str = Query("3mo"),
    interval: str = Query("1d")
):
    df = fetch_historical_data(symbol, period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")
    df = df.reset_index()
    df["SMA"] = sma(df["Close"], window)
    df["Date"] = df["Date"].astype(str)
    return JSONResponse(content=df[["Date", "Close", "SMA"]].to_dict(orient="records"))


@app.get("/indicator/{symbol}/rsi")
async def get_rsi(
    symbol: str,
    window: int = Query(14, description="RSI window"),
    period: str = Query("3mo"),
    interval: str = Query("1d")
):
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(
                status_code=404, detail="No data returned for symbol/params.")
        if "Close" not in df.columns:
            raise HTTPException(
                status_code=400, detail="No 'Close' column in fetched data.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df["RSI"] = rsi(df["Close"], window)
        df["Date"] = df["Date"].astype(str)

        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.where(pd.notnull(df), None)

        records = df[["Date", "Close", "RSI"]].to_dict(orient="records")

        def make_json_safe(obj):
            if isinstance(obj, list):
                return [make_json_safe(x) for x in obj]
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            if isinstance(obj, (float, np.floating)):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return float(obj)
            return obj

        safe_records = make_json_safe(records)
        return JSONResponse(content=safe_records)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Internal error computing RSI: {e}")


@app.get("/strategy/{symbol}/moving-average")
async def moving_average_strategy(
    symbol: str,
    short_window: int = Query(20, description="Short SMA window"),
    long_window: int = Query(50, description="Long SMA window"),
    period: str = Query("6mo"),
    interval: str = Query("1d")
):
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data returned.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"]).copy()

        df = moving_average_crossover(df, short_window, long_window)
        df["Date"] = df["Date"].astype(str)

        df = df.replace([np.inf, -np.inf], np.nan)

        records = df[["Date", "Close", "short_sma", "long_sma",
                      "signal", "crossover"]].to_dict(orient="records")

        def make_json_safe(obj):
            if isinstance(obj, list):
                return [make_json_safe(x) for x in obj]
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating, float)):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return float(obj)
            if isinstance(obj, (np.bool_, bool)):
                return bool(obj)
            return obj

        safe_records = make_json_safe(records)
        return JSONResponse(content=safe_records)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error computing moving average strategy: {e}")


@app.get("/backtest/{symbol}/moving-average")
async def backtest_moving_average(
    symbol: str,
    short_window: int = Query(20, description="Short SMA window"),
    long_window: int = Query(50, description="Long SMA window"),
    period: str = Query("6mo"),
    interval: str = Query("1d"),
    initial_balance: float = Query(10000.0, description="Starting cash")
):
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data returned.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"]).copy()

        df = moving_average_crossover(df, short_window, long_window)
        results = backtest_strategy(df, initial_balance)

        return JSONResponse(content=results)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error running backtest: {e}")


@app.get("/strategy/{symbol}/rsi")
async def rsi_strategy_endpoint(
    symbol: str,
    lower: int = Query(30, description="RSI lower threshold (buy zone)"),
    upper: int = Query(70, description="RSI upper threshold (sell zone)"),
    window: int = Query(14, description="RSI window size"),
    period: str = Query("6mo"),
    interval: str = Query("1d")
):
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data returned.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"]).copy()

        df = rsi_momentum_strategy(df, lower, upper, window)
        df["Date"] = df["Date"].astype(str)

        records = df[["Date", "Close", "RSI", "signal"]
                     ].to_dict(orient="records")

        def make_json_safe(obj):
            import math
            import numpy as np
            if isinstance(obj, list):
                return [make_json_safe(x) for x in obj]
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            if isinstance(obj, (float, np.floating)):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return float(obj)
            return obj

        safe_records = make_json_safe(records)
        return JSONResponse(content=safe_records)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error computing RSI strategy: {e}")


@app.get("/backtest/{symbol}/rsi")
async def backtest_rsi_strategy(
    symbol: str,
    lower: int = Query(30, description="RSI lower threshold (buy zone)"),
    upper: int = Query(70, description="RSI upper threshold (sell zone)"),
    window: int = Query(14, description="RSI window size"),
    period: str = Query("6mo"),
    interval: str = Query("1d"),
    initial_balance: float = Query(10000.0)
):
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data returned.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"]).copy()

        df = rsi_momentum_strategy(df, lower, upper, window)
        results = backtest_strategy(df, initial_balance)

        return JSONResponse(content=results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error running RSI backtest: {e}")


@app.get("/visualize/{symbol}/{strategy}", response_class=HTMLResponse)
async def visualize_strategy(
    symbol: str,
    strategy: str,
    period: str = Query("6mo"),
    interval: str = Query("1d")
):
    """
    Generates a chart (PNG) showing price + buy/sell signals for the given strategy.
    """
    try:
        df = fetch_historical_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            raise HTTPException(
                status_code=404, detail="No data returned for symbol/params.")

        df = df.reset_index()
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Close"]).copy()

        if strategy.lower() == "sma":
            from app.strategies.moving_average import moving_average_crossover
            df = moving_average_crossover(df)
            strategy_name = "Simple Moving Average"
        elif strategy.lower() == "rsi":
            from app.strategies.rsi_strategy import rsi_momentum_strategy
            df = rsi_momentum_strategy(df)
            strategy_name = "RSI Momentum"
        else:
            raise HTTPException(
                status_code=400, detail="Invalid strategy. Use 'sma' or 'rsi'.")

        if "Date" in df.columns:
            df["Date"] = df["Date"].astype(str)
        else:
            df = df.reset_index()
            df["Date"] = df.index.astype(str)

        if "signal" not in df.columns:
            df["signal"] = 0

        img_base64 = plot_strategy(df, symbol, strategy_name)
        html = f"""
        <html>
        <body style='text-align:center; background-color:#111; color:white;'>
            <h2>{symbol} - {strategy_name} Strategy</h2>
            <img src='data:image/png;base64,{img_base64}' style='max-width:90%; border:2px solid white; border-radius:8px;'/>
        </body>
        </html>
        """
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Visualization error: {e}")

# --------------------------
# WebSocket endpoint for clients to receive ticks & portfolio updates
# --------------------------


@app.websocket("/ws/{symbol}")
async def websocket_endpoint(websocket: WebSocket, symbol: str):
    await websocket.accept()
    await ws_manager.connect(symbol, websocket)
    try:
        while True:
            try:
                data = await websocket.receive_text()
                # Optional: handle simple ping messages
                if data.lower() == "ping":
                    await websocket.send_text("pong")
                else:
                    await websocket.send_text(f"echo: {data}")
            except Exception as inner_e:
                print(f"[WebSocket Error] {inner_e}")
                break
    except WebSocketDisconnect:
        print(f"[WebSocket] {symbol} disconnected.")
    finally:
        await ws_manager.disconnect(symbol, websocket)

# --------------------------
# Control pseudo-live stream
# --------------------------


@app.post("/stream/start")
async def api_start_stream(symbol: str, period: str = "3mo", interval: str = "1d", speed: float = 1.0):
    """
    Start replaying historical data for `symbol` and broadcasting ticks to /ws/{symbol}.
    speed = seconds between bars (float)
    """
    loop = asyncio.get_running_loop()
    start_stream_background(loop, symbol, period=period,
                            interval=interval, speed=speed)
    return {"status": "started", "symbol": symbol.upper(), "speed": speed}


@app.post("/stream/stop")
async def api_stop_stream():
    stop_stream()
    return {"status": "stopped"}


@app.get("/stream/status")
async def api_stream_status():
    return stream_status()

# --------------------------
# Control paper trader (server-side) that executes trades on the replay
# --------------------------


@app.post("/simulate/start")
async def api_start_simulation(symbol: str,
                               strategy: str = "sma",
                               speed: float = 1.0,
                               initial_balance: float = 10000.0,
                               period: str = "3mo",
                               interval: str = "1d",
                               short_window: int = 20,
                               long_window: int = 50,
                               lower: int = 30,
                               upper: int = 70,
                               window: int = 14):
    logger.info(
        f"▶️ Starting live trader for {symbol.upper()} with strategy {strategy}")
    if trader_state["running"]:
        return {"status": "already_running", "symbol": trader_state["symbol"]}
    params = {
        "initial_balance": initial_balance,
        "period": period,
        "interval": interval,
        "short_window": short_window,
        "long_window": long_window,
        "lower": lower,
        "upper": upper,
        "window": window,
        "speed": speed
    }

    trader_state.update({
        "running": True,
        "symbol": symbol.upper(),
        "strategy": strategy,
        "balance": initial_balance,
        "position": 0,
        "last_price": None,
        "pnl": 0,
        "trades": 0
    })

    asyncio.create_task(run_live_trader(symbol, strategy, params, ws_manager))
    return {"status": "live_simulation_started", "symbol": symbol.upper(), "strategy": strategy}


@app.post("/simulate/stop")
async def api_stop_simulation():
    stop_paper_trader()
    logger.info("⏹️ Stopped live trader (via API)")
    return {"status": "simulation_stopped"}


@app.get("/simulate/status")
async def api_simulation_status():
    from app.paper_trader import trader_state
    return trader_state


# --------------------------
# Read trades / portfolio from SQLite
# --------------------------


@app.get("/trades/{symbol}")
async def api_get_trades(symbol: str):
    ensure_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT dt, action, price, quantity FROM trades WHERE symbol = ? ORDER BY id", (symbol.upper(),))
    rows = c.fetchall()
    conn.close()
    trades = [{"dt": r[0], "action": r[1], "price": float(
        r[2]), "quantity": float(r[3])} for r in rows]
    return {"symbol": symbol.upper(), "trades": trades}


@app.get("/portfolio/{symbol}")
async def api_get_portfolio(symbol: str):
    ensure_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT dt, cash, position, position_value, total_value FROM portfolio_snapshot WHERE symbol = ? ORDER BY id", (symbol.upper(),))
    rows = c.fetchall()
    conn.close()
    snapshots = [{"dt": r[0], "cash": float(r[1]), "position": float(
        r[2]), "position_value": float(r[3]), "total_value": float(r[4])} for r in rows]
    return {"symbol": symbol.upper(), "snapshots": snapshots}


@app.get("/portfolio/{symbol}/summary")
async def api_get_portfolio_summary(symbol: str):
    """
    Return a high-level portfolio summary:
    - Latest total value
    - Cash
    - Position
    - Average entry price
    - Realized & unrealized PnL
    - Total trades count
    """
    ensure_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()

    c.execute("""
        SELECT dt, cash, position, position_value, total_value 
        FROM portfolio_snapshot 
        WHERE symbol = ? 
        ORDER BY id DESC LIMIT 1
    """, (symbol.upper(),))
    last_snap = c.fetchone()

    c.execute("""
        SELECT action, price, quantity FROM trades WHERE symbol = ?
    """, (symbol.upper(),))
    trades = c.fetchall()
    conn.close()

    if not last_snap:
        raise HTTPException(
            status_code=404, detail="No portfolio data found for symbol.")

    _, cash, position, position_value, total_value = last_snap

    total_trades = len(trades)
    realized_pnl = 0.0
    avg_entry_price = 0.0
    unrealized_pnl = 0.0

    buy_trades = [(p, q) for (a, p, q) in trades if a == "BUY"]
    if buy_trades:
        total_qty = sum(q for _, q in buy_trades)
        if total_qty > 0:
            avg_entry_price = sum(p * q for p, q in buy_trades) / total_qty

    sell_trades = [(p, q) for (a, p, q) in trades if a == "SELL"]
    if sell_trades and buy_trades:
        realized_pnl = sum((sell_p - avg_entry_price) *
                           sell_q for sell_p, sell_q in sell_trades)

    if position > 0 and avg_entry_price > 0:
        unrealized_pnl = (position_value - (position * avg_entry_price))

    total_pnl = realized_pnl + unrealized_pnl

    return {
        "symbol": symbol.upper(),
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "position": round(position, 2),
        "avg_entry_price": round(avg_entry_price, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "trades": total_trades,
    }
