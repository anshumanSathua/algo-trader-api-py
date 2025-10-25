import asyncio
import sqlite3
import threading
import pandas as pd
from app.data_fetcher import fetch_historical_data
from app.strategies.moving_average import moving_average_crossover
from app.strategies.rsi_strategy import rsi_momentum_strategy
import logging


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


DB_PATH = "data/trades.db"

_db_init_lock = threading.Lock()

trader_state = {
    "running": False,
    "symbol": None,
    "strategy": None,
    "balance": 10000.0,
    "position": 0.0,
    "last_price": None,
    "pnl": 0.0,
    "trades": 0
}


def ensure_db():
    with _db_init_lock:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                dt TEXT,
                action TEXT,
                price REAL,
                quantity REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                dt TEXT,
                cash REAL,
                position REAL,
                position_value REAL,
                total_value REAL
            )
        """)
        conn.commit()
        conn.close()


ensure_db()

_sim_state = {
    "running": False,
    "symbol": None,
    "strategy": None,
    "task": None,
    "lock": asyncio.Lock()
}


async def _paper_loop(symbol: str, strategy_name: str, params: dict, speed: float, ws_manager=None):
    """
    Subscribe to historical df and simulate ticks (server-side replay).
    We will use the same fetcher to iterate rows, compute signals, and execute.
    """
    try:
        df = fetch_historical_data(symbol, period=params.get(
            "period", "3mo"), interval=params.get("interval", "1d"))
        if df is None or df.empty:
            return
        df = df.reset_index().copy()
        if strategy_name.lower() == "sma":
            short = params.get("short_window", 20)
            long = params.get("long_window", 50)
            df = moving_average_crossover(
                df, short_window=short, long_window=long)
        else:
            lower = params.get("lower", 30)
            upper = params.get("upper", 70)
            window = params.get("window", 14)
            df = rsi_momentum_strategy(
                df, lower=lower, upper=upper, window=window)

        cash = float(params.get("initial_balance", 10000.0))
        position = 0.0  # shares
        ensure_db()
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        c = conn.cursor()

        for _, row in df.iterrows():
            sig = int(row.get("signal", 0))
            price = float(row["Close"])
            dt_value = row["Date"]
            if isinstance(dt_value, pd.Timestamp):
                dt = dt_value.strftime("%Y-%m-%d")
            elif hasattr(dt_value, "item"):  # numpy.datetime64
                dt = pd.Timestamp(dt_value).strftime("%Y-%m-%d")
            else:
                dt = str(dt_value)

            if sig == 1 and position == 0:
                qty = cash / price if price > 0 else 0
                if qty > 0:
                    position = qty
                    cash = 0.0
                    c.execute("INSERT INTO trades (symbol, dt, action, price, quantity) VALUES (?, ?, ?, ?, ?)",
                              (symbol.upper(), dt, "BUY", price, qty))
                    conn.commit()

            elif sig == -1 and position > 0:
                qty = position
                cash = position * price
                position = 0.0
                c.execute("INSERT INTO trades (symbol, dt, action, price, quantity) VALUES (?, ?, ?, ?, ?)",
                          (symbol.upper(), dt, "SELL", price, qty))
                conn.commit()

            total_value = cash + (position * price)

            c.execute("INSERT INTO portfolio_snapshot (symbol, dt, cash, position, position_value, total_value) VALUES (?, ?, ?, ?, ?, ?)",
                      (symbol.upper(), dt, float(cash), float(position), float(position * price), float(total_value)))
            conn.commit()

            if _ % 100 == 0:
                c.execute("VACUUM;")
                conn.commit()

            trader_state.update({
                "running": True,
                "symbol": symbol.upper(),
                "strategy": strategy_name,
                "balance": round(cash, 2),
                "position": round(position, 4),
                "last_price": round(price, 2),
                "pnl": round(total_value - params.get("initial_balance", 10000.0), 2),
                "trades": len(c.execute("SELECT id FROM trades WHERE symbol = ?", (symbol.upper(),)).fetchall())
            })

            if ws_manager:
                await ws_manager.broadcast_tick(symbol, {
                    "type": "portfolio_update",
                    "Date": dt,
                    "cash": cash,
                    "position": position,
                    "position_value": position * price,
                    "total_value": total_value
                })

            await asyncio.sleep(speed)

    finally:
        _sim_state.update({"running": False, "symbol": None,
                          "strategy": None, "task": None})
        if 'conn' in locals():
            conn.close()


def start_paper_trader(loop, symbol, strategy, params, speed, ws_manager):
    """
    Starts the async simulation task for paper trading.
    """
    global _sim_state, trader_state

    if _sim_state["running"]:
        print("Simulation already running — ignoring start request.")
        return

    ensure_db()

    trader_state.update({
        "running": True,
        "symbol": symbol.upper(),
        "strategy": strategy,
        "balance": params.get("initial_balance", 10000),
        "position": 0,
        "last_price": None,
        "pnl": 0.0,
        "trades": 0
    })

    async def run_trader_wrapper():
        await _paper_loop(symbol, strategy, params, speed, ws_manager)

        trader_state["running"] = False
        trader_state["symbol"] = None
        trader_state["strategy"] = None

    task = loop.create_task(run_trader_wrapper())

    _sim_state.update({
        "running": True,
        "symbol": symbol.upper(),
        "strategy": strategy,
        "task": task
    })

    print(
        f"✅ Simulation started for {symbol.upper()} using {strategy.upper()} strategy.")


async def run_live_trader(symbol: str, strategy: str, params: dict, ws_manager):
    import logging
    logging.info(
        f"▶️ Starting live trader for {symbol.upper()} with strategy {strategy.upper()}")

    trader_state.update({
        "running": True,
        "symbol": symbol.upper(),
        "strategy": strategy,
        "balance": float(params.get("initial_balance", 10000)),
        "position": 0.0,
        "last_price": None,
        "pnl": 0.0,
        "trades": 0
    })

    ensure_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()

    try:
        async for tick in ws_manager.tick_stream(symbol):
            price = tick.get("Close")
            dt = tick.get("Date")
            if price is None:
                continue

            trader_state["last_price"] = price
            signal = 0

            df = fetch_historical_data(symbol, period=params.get("period", "3mo"),
                                       interval=params.get("interval", "1d"))
            df = df.reset_index()
            if strategy.lower() == "sma":
                df = moving_average_crossover(df,
                                              short_window=params.get(
                                                  "short_window", 20),
                                              long_window=params.get("long_window", 50))
            else:
                df = rsi_momentum_strategy(df,
                                           lower=params.get("lower", 30),
                                           upper=params.get("upper", 70),
                                           window=params.get("window", 14))
            if not df.empty:
                signal = int(df.iloc[-1].get("signal", 0))

            cash = trader_state["balance"]
            position = trader_state["position"]

            if signal == 1 and position == 0:
                qty = cash / price if price > 0 else 0
                if qty > 0:
                    position = qty
                    cash = 0.0
                    trader_state["trades"] += 1
                    logging.info(f"[BUY] {symbol.upper()} @ {price:.2f}")
                    c.execute("INSERT INTO trades (symbol, dt, action, price, quantity) VALUES (?, ?, ?, ?, ?)",
                              (symbol.upper(), dt, "BUY", price, qty))
                    conn.commit()

            elif signal == -1 and position > 0:
                cash = position * price
                logging.info(f"[SELL] {symbol.upper()} @ {price:.2f}")
                c.execute("INSERT INTO trades (symbol, dt, action, price, quantity) VALUES (?, ?, ?, ?, ?)",
                          (symbol.upper(), dt, "SELL", price, position))
                conn.commit()
                position = 0.0
                trader_state["trades"] += 1

            total_value = cash + (position * price)
            trader_state.update({
                "balance": cash,
                "position": position,
                "pnl": total_value - float(params.get("initial_balance", 10000))
            })

            c.execute("INSERT INTO portfolio_snapshot (symbol, dt, cash, position, position_value, total_value) VALUES (?, ?, ?, ?, ?, ?)",
                      (symbol.upper(), dt, cash, position, position * price, total_value))
            conn.commit()

            await asyncio.sleep(0.2)

    except asyncio.CancelledError:
        logging.warning(f"⚠️ Simulation for {symbol} was cancelled.")
    except Exception as e:
        logging.error(f"[Trader Error] {e}")
    finally:
        logging.info(f"⏹️ Live trader stopped for {symbol.upper()}")
        try:
            price = trader_state.get("last_price") or 0
            cash = trader_state.get("balance", 0)
            position = trader_state.get("position", 0)
            total_value = cash + (position * price)
            c.execute("""
                INSERT INTO portfolio_snapshot (symbol, dt, cash, position, position_value, total_value)
                VALUES (?, datetime('now'), ?, ?, ?, ?)
            """, (symbol.upper(), cash, position, position * price, total_value))
            conn.commit()
            logging.info(
                f"[Portfolio] Final snapshot saved for {symbol.upper()} @ {total_value:.2f}")

            if ws_manager:
                await ws_manager.broadcast_tick(symbol, {
                    "type": "portfolio_final",
                    "symbol": symbol.upper(),
                    "cash": cash,
                    "position": position,
                    "position_value": position * price,
                    "total_value": total_value,
                    "pnl": trader_state.get("pnl", 0.0),
                })

        except Exception as e:
            logging.error(f"[Portfolio Snapshot Error] {e}")
        finally:
            trader_state.update({
                "running": False,
                "symbol": None,
                "strategy": None
            })
            if not trader_state["running"]:
                logging.info(
                    f"⚠️ Trader was already marked stopped for {symbol}")

            conn.close()


def stop_paper_trader():
    import logging
    from app.live_feed import ws_manager

    global _sim_state, trader_state
    logging.info("⏹️ Stopping paper trader manually...")

    _sim_state["running"] = False
    trader_state["running"] = False

    task = _sim_state.get("task")
    if task and not task.done():
        task.cancel()

    asyncio.create_task(ws_manager.broadcast_tick(
        trader_state.get("symbol") or "UNKNOWN",
        {"type": "stopped", "message": "Simulation stopped by user."}
    ))

    trader_state.update({"symbol": None, "strategy": None})
    _sim_state.update({"task": None, "symbol": None, "strategy": None})

    logging.info("✅ Paper trader stopped gracefully and clients notified.")
