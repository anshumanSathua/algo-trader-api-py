# 🧠 Algo Trader Backend

A **FastAPI-based algorithmic trading simulator** that mimics real-time market conditions using Yahoo Finance data.  

It supports **live tick streaming**, **SMA/RSI trading strategies**, **paper trading**, and **portfolio tracking** — all through a clean API and WebSocket interface.

---

## 🌐 Live Demo

Check out the live API: [https://algo-trader-api-py.onrender.com/docs#/](https://algo-trader-api-py.onrender.com/docs#/)

[![Live Demo](https://img.shields.io/badge/-LIVE_DEMO-2ea44f?style=for-the-badge)](https://algo-trader-api-py.onrender.com/docs#/)

## 🚀 Features

- 📈 **Live Market Feed** – Stream historical data as live ticks from Yahoo Finance  
- 🤖 **Trading Strategies** – Built-in SMA and RSI-based strategies  
- 💰 **Paper Trading Engine** – Executes simulated trades with a virtual balance  
- 📊 **Portfolio Tracking** – Maintains trades and snapshots in SQLite  
- 🔄 **Start/Stop Simulation** – Full control over trading lifecycle  
- 🌐 **WebSocket Feed** – Real-time tick updates and final portfolio snapshot  
- 🧩 **Modular Design** – Easy to extend with new strategies

---

## 🛠️ Tech Stack

- FastAPI – API framework

- AsyncIO – Concurrency engine

- SQLite – Lightweight local database

- Yahoo Finance (yfinance) – Historical data provider

- Python Logging – Structured runtime logs
---

## ⚙️ Installation & Setup

### 1. Create and activate virtual environment
```bash
python -m venv venv

venv\Scripts\activate
```
### 2. Install dependencies
```
pip install -r requirements.txt
````
### 3. Run Server

```bash
uvicorn app.main:app --reload
```

## 📡 API Overview
### ▶️ Start Data Stream
```
POST /stream/start?symbol=AAPL&period=6mo&interval=1d&speed=0.2
```
Starts a live tick feed using Yahoo Finance data.
### ▶️ Start Simulation

```
POST /simulate/start?symbol=AAPL&strategy=sma
```
Begins paper trading using the selected strategy.
Supports both SMA and RSI.

Optional parameters:

| Param                          | Description               | Default |
| ------------------------------ | ------------------------- | ------- |
| `speed`                        | Tick playback speed (sec) | 1.0     |
| `initial_balance`              | Starting balance          | 10000   |
| `period`                       | Yahoo data range          | `3mo`   |
| `interval`                     | Candle interval           | `1d`    |
| `short_window` / `long_window` | SMA strategy config       | 20 / 50 |
| `lower` / `upper`              | RSI strategy thresholds   | 30 / 70 |
| `window`                       | RSI lookback period       | 14      |


### ⏹ Stop Simulation
```
POST /simulate/stop
```
Stops live trading and stores the final portfolio snapshot.

### 📊 Get Portfolio Snapshot
```
GET /portfolio/{symbol}
```
Returns the latest portfolio details for a given symbol.

### 💹 Get Portfolio Summary
```
GET /portfolio/summary
```
Returns all tracked symbols with balances and PnL.

### 🔌 WebSocket Feed

Connect to
```
ws://127.0.0.1:8000/ws/{symbol}
```
You’ll receive:

 - Tick data in real-time

 - A final portfolio snapshot when the stream ends

Example tick message:
```json
{
  "type": "tick",
  "symbol": "AAPL",
  "Date": "2025-10-10",
  "Open": 189.55,
  "High": 190.78,
  "Low": 188.90,
  "Close": 190.12,
  "Volume": 51230000
}
```
Example final portfolio:

```json
{
  "type": "portfolio",
  "symbol": "AAPL",
  "balance": 10814.53,
  "pnl": 814.53,
  "trades": 4
}
```

### 🗄 Database Schema
|Table	|Columns
|-------|----------|
|trades	|id, symbol, date, side, price, qty
|portfolio_snapshot	|id, symbol, timestamp, position, price, balance, total_value

Stored automatically at:
```
data/trades.db
```

## 🧠 Author

Built by [Anshuman](https://github.com/anshumanSathua) with ❤️
