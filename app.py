from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import requests
import websocket
import threading
import json
import time
import os

app = Flask(__name__)

# Production startup: Gunicorn imports app.py, so initialize market data here.
_started = False
_start_lock = threading.Lock()

def start_market_engine():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

        print("[STARTUP] Loading Binance market history...", flush=True)
        load_history()

        print("[STARTUP] Starting Binance WebSocket...", flush=True)
        threading.Thread(target=websocket_loop, daemon=True).start()

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

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


def send_chat(message):
    print("[CHAT]", message, flush=True)

    socketio.emit("trading_chat", {
        "time": int(time.time() * 1000),
        "message": message
    })


def load_history(symbol):
    global candles

    try:
        url = "https://api.binance.com/api/v3/klines"

        response = requests.get(
            url,
            params={
                "symbol": symbol,
                "interval": INTERVAL,
                "limit": 100
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            raise Exception(f"Unexpected Binance response: {data}")

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

        print(
            f"[HISTORY] Loaded {len(candles)} candles for {symbol}",
            flush=True
        )

        send_chat(
            f"{symbol} • Loaded {len(candles)} historical candles"
        )

        return True

    except Exception as e:
        print("[HISTORY ERROR]", repr(e), flush=True)
        send_chat(f"{symbol} • History error: {e}")
        return False


def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        value = (price - value) * multiplier + value

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

    if fast < slow and last < slow:
        return {
            "signal": "DOWN",
            "reason": "EMA 9 below EMA 20"
        }

    return {
        "signal": "NEUTRAL",
        "reason": "Mixed market conditions"
    }


def send_state():
    result = analyse()

    payload = {
        "symbol": SYMBOL,
        "candles": candles[-100:],
        "signal": result["signal"],
        "reason": result["reason"]
    }

    print(
        f"[STATE] {SYMBOL} candles={len(candles)} "
        f"signal={result['signal']}",
        flush=True
    )

    socketio.emit("market_data", payload)


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

        send_state()

        if k["x"]:
            result = analyse()

            send_chat(
                f"{SYMBOL} • Candle closed • "
                f"{result['signal']} • {result['reason']}"
            )

    except Exception as e:
        print("[MESSAGE ERROR]", repr(e), flush=True)


def on_error(ws_app, error):
    print("[BINANCE WS ERROR]", repr(error), flush=True)
    send_chat(f"{SYMBOL} • Binance WebSocket error: {error}")


def on_close(ws_app, code, message):
    print(
        f"[BINANCE WS CLOSED] code={code} message={message}",
        flush=True
    )

    send_chat(f"{SYMBOL} • Binance stream disconnected")


def on_open(ws_app):
    print(
        f"[BINANCE WS CONNECTED] {SYMBOL}",
        flush=True
    )

    send_chat(f"{SYMBOL} • Binance live WebSocket connected")

    send_state()


def websocket_loop():
    global ws

    while True:
        try:
            symbol = SYMBOL.lower()

            url = (
                "wss://stream.binance.com:9443/ws/"
                f"{symbol}@kline_{INTERVAL}"
            )

            print(
                f"[BINANCE CONNECTING] {url}",
                flush=True
            )

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
            print(
                "[WEBSOCKET LOOP ERROR]",
                repr(e),
                flush=True
            )

            send_chat(
                f"{SYMBOL} • WebSocket reconnecting..."
            )

        time.sleep(5)


\n@app.before_request
def ensure_market_engine():
    start_market_engine()
\n@app.route("/")
def home():
    return render_template("index.html")


@app.route("/select", methods=["POST"])
def select_market():
    global SYMBOL, ws

    data = request.get_json(silent=True) or {}

    new_symbol = str(
        data.get("symbol", "")
    ).upper()

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


@socketio.on("connect")
def handle_connect():
    print(
        f"[CLIENT CONNECTED] {SYMBOL}",
        flush=True
    )

    socketio.emit("trading_chat", {
        "time": int(time.time() * 1000),
        "message": "Bot connected to live market stream."
    })

    send_state()


if __name__ == "__main__":
    print("[SERVER] Starting Live Trading Bot", flush=True)

    load_history(SYMBOL)

    threading.Thread(
        target=websocket_loop,
        daemon=True
    ).start()

    port = int(
        os.environ.get("PORT", 5000)
    )

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        allow_unsafe_werkzeug=True
    )

@app.route("/debug")
def debug():
    result = {
        "symbol": SYMBOL,
        "candles": len(candles),
        "last_candle": candles[-1] if candles else None,
        "analysis": analyse()
    }

    # Direct Binance REST diagnostic
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "limit": 5
            },
            timeout=15
        )

        result["binance_status"] = r.status_code
        result["binance_ok"] = r.status_code == 200

        if r.status_code == 200:
            data = r.json()
            result["binance_candles"] = len(data)
            result["binance_last_close"] = data[-1][4] if data else None
        else:
            result["binance_response"] = r.text[:500]

    except Exception as e:
        result["binance_ok"] = False
        result["binance_error"] = str(e)

    return jsonify(result)
