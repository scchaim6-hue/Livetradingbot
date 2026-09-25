from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import requests
import websocket
import threading
import json
import time
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

SYMBOL = "BTCUSDT"
INTERVAL = "1m"

candles = []
ws = None
ws_lock = threading.Lock()

ALLOWED_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT"
}


def load_history(symbol):
    global candles

    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": INTERVAL,
                "limit": 100
            },
            timeout=10
        )

        r.raise_for_status()
        data = r.json()

        candles = [
            {
                "time": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            }
            for x in data
        ]

        print(f"Loaded {len(candles)} candles for {symbol}")

    except Exception as e:
        print("History error:", e)


def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        value = (
            price - value
        ) * multiplier + value

    return value


def analyse():
    if len(candles) < 20:
        return {
            "signal": "WAIT",
            "reason": "Collecting market data"
        }

    closes = [c["close"] for c in candles]

    fast = ema(closes, 9)
    slow = ema(closes, 20)

    last = closes[-1]

    if fast is None or slow is None:
        return {
            "signal": "WAIT",
            "reason": "Calculating indicators"
        }

    if fast > slow and last > fast:
        return {
            "signal": "UP",
            "reason": "EMA 9 above EMA 20"
        }

    if fast < slow and last < fast:
        return {
            "signal": "DOWN",
            "reason": "EMA 9 below EMA 20"
        }

    return {
        "signal": "NEUTRAL",
        "reason": "Mixed market conditions"
    }


def send_state():
    if not candles:
        return

    result = analyse()

    socketio.emit(
        "market_data",
        {
            "symbol": SYMBOL,
            "candles": candles[-100:],
            "signal": result["signal"],
            "reason": result["reason"]
        }
    )


def send_chat(message):
    socketio.emit(
        "trading_chat",
        {
            "time": int(time.time() * 1000),
            "message": message
        }
    )


def on_message(ws_app, message):
    global candles

    try:
        data = json.loads(message)
        k = data.get("k")

        if not k:
            return

        candle = {
            "time": int(k["t"]),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"])
        }

        if candles and candles[-1]["time"] == candle["time"]:
            candles[-1] = candle
        else:
            candles.append(candle)

        if len(candles) > 100:
            candles = candles[-100:]

        result = analyse()

        send_state()

        if k["x"]:
            send_chat(
                f"{SYMBOL} • Candle closed • "
                f"{result['signal']} • {result['reason']}"
            )

    except Exception as e:
        print("WebSocket message error:", e)


def on_error(ws_app, error):
    print("WebSocket error:", error)


def on_close(ws_app, code, message):
    print("WebSocket closed")


def on_open(ws_app):
    print("WebSocket connected:", SYMBOL)
    send_chat(f"{SYMBOL} • Live WebSocket connected")


def websocket_loop():
    global ws

    while True:
        try:
            url = (
                "wss://stream.binance.com:9443/ws/"
                f"{SYMBOL.lower()}@kline_{INTERVAL}"
            )

            print("Connecting:", url)

            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws.run_forever(
                ping_interval=20,
                ping_timeout=10
            )

        except Exception as e:
            print("WebSocket connection error:", e)

        time.sleep(3)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/select", methods=["POST"])
def select_market():
    global SYMBOL, ws

    data = request.get_json(silent=True) or {}
    new_symbol = str(data.get("symbol", "")).upper()

    if new_symbol not in ALLOWED_SYMBOLS:
        return jsonify({
            "ok": False,
            "error": "Unsupported market"
        }), 400

    SYMBOL = new_symbol

    try:
        if ws:
            ws.close()
    except Exception:
        pass

    load_history(SYMBOL)
    send_state()
    send_chat(f"Market changed → {SYMBOL}")

    return jsonify({
        "ok": True,
        "symbol": SYMBOL
    })


if __name__ == "__main__":
    load_history(SYMBOL)

    threading.Thread(
        target=websocket_loop,
        daemon=True
    ).start()

    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True
    )
