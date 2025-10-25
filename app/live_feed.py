import asyncio
import pandas as pd
import yfinance as yf
from typing import Dict, Any
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.active_connections: dict[str, list] = {}
        self._tick_queues: dict[str, asyncio.Queue] = {}

    async def connect(self, symbol: str, websocket: WebSocket):
        self.active_connections.setdefault(symbol, []).append(websocket)

    async def disconnect(self, symbol: str, websocket: WebSocket):
        if symbol in self.active_connections:
            self.active_connections[symbol].remove(websocket)
            if not self.active_connections[symbol]:
                del self.active_connections[symbol]

    async def broadcast_tick(self, symbol: str, tick_data: dict):
        if symbol in self.active_connections:
            for ws in self.active_connections[symbol]:
                await ws.send_json(tick_data)

        if symbol in self._tick_queues:
            await self._tick_queues[symbol].put(tick_data)

    async def tick_stream(self, symbol: str):
        """
        Async generator that yields tick dicts as they arrive.
        The paper trader uses this to 'subscribe' internally.
        """
        q = self._tick_queues.setdefault(symbol, asyncio.Queue())
        while _stream_state["running"] or not q.empty():
            try:
                tick = await asyncio.wait_for(q.get(), timeout=1.0)
                yield tick
            except asyncio.TimeoutError:
                if not _stream_state["running"] and q.empty():
                    break
        print(f"[TickStream] {symbol} closed.")


ws_manager = WebSocketManager()

_stream_state = {
    "running": False,
    "task": None,
    "symbol": None,
    "speed": 1.0
}


async def _stream_loop(symbol: str, period: str = "3mo", interval: str = "1d", speed: float = 1.0):
    try:
        df = yf.download(symbol, period=period,
                         interval=interval, progress=False)
        if df.empty:
            print(f"[Stream] No data found for {symbol}")
            return
        df = df.reset_index()
        _stream_state["running"] = True
        _stream_state["symbol"] = symbol

        for _, row in df.iterrows():
            if not _stream_state["running"]:
                break
            tick = {
                "type": "tick",
                "symbol": symbol.upper(),
                "Date": str(row["Date"]),
                "Open": float(row["Open"].iloc[0]) if hasattr(row["Open"], "iloc") else float(row["Open"]),
                "High": float(row["High"].iloc[0]) if hasattr(row["High"], "iloc") else float(row["High"]),
                "Low": float(row["Low"].iloc[0]) if hasattr(row["Low"], "iloc") else float(row["Low"]),
                "Close": float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"]),
                "Volume": int(row["Volume"].iloc[0]) if hasattr(row["Volume"], "iloc") else int(row["Volume"]),

            }
            await ws_manager.broadcast_tick(symbol, tick)
            await asyncio.sleep(speed)
        print(f"[Stream] Completed feed for {symbol}.")

        await ws_manager.broadcast_tick(symbol, {
            "type": "stopped",
            "message": f"Feed completed for {symbol}."
        })
        print(f"[TickStream] {symbol} closed.")

    except Exception as e:
        print(f"[Stream Error] {e}")
    finally:
        _stream_state["running"] = False
        _stream_state["symbol"] = None
        _stream_state["task"] = None

        if symbol in ws_manager._tick_queues:
            ws_manager._tick_queues.pop(symbol, None)
        print(f"[Cleanup] Queue cleared for {symbol}")


def start_stream_background(loop, symbol: str, period: str = "3mo", interval: str = "1d", speed: float = 1.0):
    if _stream_state["running"]:
        print("[Stream] Already running.")
        return
    _stream_state["speed"] = speed
    _stream_state["task"] = loop.create_task(
        _stream_loop(symbol, period, interval, speed))


def stop_stream():
    _stream_state["running"] = False
    task = _stream_state.get("task")
    if task and not task.done():
        task.cancel()
    _stream_state.update({"task": None, "symbol": None})


def stream_status():
    return {
        "running": _stream_state["running"],
        "symbol": _stream_state["symbol"],
        "speed": _stream_state["speed"]
    }
