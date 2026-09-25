from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import requests
import threading
import time
import os

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

SYMBOL = "BTCUSDT"
INTERVAL = "1m"

candles = []
engine_started = False
engine_lock = threading.Lock()

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
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": INTERVAL,
                "limit": 200
            },
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            raise Exception("Invalid Binance response")

        new_candles = []

        for x in data:
            new_candles.append({
                "time": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            })

        candles = new_candles

        print(
            f"[HISTORY] {symbol}: {len(candles)} candles loaded",
            flush=True
        )

        send_chat(
            f"{symbol} • {len(candles)} candles loaded"
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
        "candles": candles,
        "signal": result["signal"],
        "reason": result["reason"]
    }

    socketio.emit("market_data", payload)


def update_live_candle():
    global candles

    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "limit": 2
            },
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        if not data:
            return

        for x in data:
            candle = {
                "time": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            }

            if candles and candles[-1]["time"] == candle["time"]:
                candles[-1] = candle

            elif not candles or candle["time"] > candles[-1]["time"]:
                candles.append(candle)

                print(
                    f"[NEW CANDLE] {SYMBOL} "
                    f"{candle['open']} → {candle['close']}",
                    flush=True
                )

                result = analyse()

                send_chat(
                    f"{SYMBOL} • New candle • "
                    f"{result['signal']} • {result['reason']}"
                )

        # Keep a large history so the chart can continue moving forward.
        if len(candles) > 1000:
            candles = candles[-1000:]

        send_state()

    except Exception as e:
        print("[LIVE DATA ERROR]", repr(e), flush=True)


def market_engine():
    global SYMBOL

    print("[ENGINE] Live market engine started", flush=True)

    while True:
        try:
            update_live_candle()
        except Exception as e:
            print("[ENGINE ERROR]", repr(e), flush=True)

        time.sleep(2)


def start_engine():
    global engine_started

    with engine_lock:
        if engine_started:
            return

        engine_started = True

        print("[STARTUP] Loading market history...", flush=True)
        load_history(SYMBOL)

        print("[STARTUP] Starting live candle engine...", flush=True)

        thread = threading.Thread(
            target=market_engine,
            daemon=True
        )

        thread.start()


@app.before_request
def ensure_engine():
    start_engine()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/select", methods=["POST"])
def select_market():
    global SYMBOL

    data = request.get_json(silent=True) or {}
    new_symbol = str(data.get("symbol", "")).upper()

    if new_symbol not in ALLOWED_SYMBOLS:
        return jsonify({
            "ok": False,
            "error": "Unsupported market"
        }), 400

    SYMBOL = new_symbol

    print(
        f"[MARKET] Changed to {SYMBOL}",
        flush=True
    )

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


@app.route("/debug")
def debug():
    result = {
        "symbol": SYMBOL,
        "candles": len(candles),
        "last_candle": candles[-1] if candles else None,
        "analysis": analyse()
    }

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
            result["binance_last_close"] = (
                data[-1][4] if data else None
            )
        else:
            result["binance_response"] = r.text[:500]

    except Exception as e:
        result["binance_ok"] = False
        result["binance_error"] = str(e)

    return jsonify(result)


if __name__ == "__main__":
    start_engine()

    port = int(os.environ.get("PORT", 5000))

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        allow_unsafe_werkzeug=True
    )
