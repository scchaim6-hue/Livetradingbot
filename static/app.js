const socket = io();

const chartElement = document.getElementById("chart");
const priceElement = document.getElementById("price");
const symbolElement = document.getElementById("symbol");
const signalElement = document.getElementById("signal");
const analysisElement = document.getElementById("analysis");
const messagesElement = document.getElementById("messages");
const connectionElement = document.getElementById("connection");
const marketSelect = document.getElementById("market");

const chart = LightweightCharts.createChart(
    chartElement,
    {
        layout: {
            background: {
                color: "#08111d"
            },
            textColor: "#9fb0c3"
        },

        grid: {
            vertLines: {
                color: "#142235"
            },
            horzLines: {
                color: "#142235"
            }
        },

        rightPriceScale: {
            borderColor: "#24364c"
        },

        timeScale: {
            borderColor: "#24364c",
            timeVisible: true,
            secondsVisible: false
        },

        crosshair: {
            mode: 0
        }
    }
);

const candleSeries = chart.addCandlestickSeries({
    upColor: "#20d889",
    downColor: "#ff5364",
    borderVisible: false,
    wickUpColor: "#20d889",
    wickDownColor: "#ff5364"
});

const volumeSeries = chart.addHistogramSeries({
    priceFormat: {
        type: "volume"
    },
    priceScaleId: ""
});

volumeSeries.priceScale().applyOptions({
    scaleMargins: {
        top: 0.8,
        bottom: 0
    }
});

window.addEventListener("resize", () => {
    chart.applyOptions({
        width: chartElement.clientWidth,
        height: chartElement.clientHeight
    });
});


function updateChart(candles) {

    const chartData = candles.map(c => ({
        time: Math.floor(c.time / 1000),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
    }));

    const volumeData = candles.map(c => ({
        time: Math.floor(c.time / 1000),
        value: c.volume,
        color: c.close >= c.open
            ? "#20d889"
            : "#ff5364"
    }));

    candleSeries.setData(chartData);
    volumeSeries.setData(volumeData);

    chart.timeScale().fitContent();

    if (candles.length) {
        priceElement.innerText =
            Number(candles[candles.length - 1].close)
                .toLocaleString(undefined, {
                    maximumFractionDigits: 8
                });
    }
}


function updateSignal(signal, reason) {

    signalElement.className =
        signal.toLowerCase();

    if (signal === "UP") {
        signalElement.innerText = "↑ UP";
    }
    else if (signal === "DOWN") {
        signalElement.innerText = "↓ DOWN";
    }
    else if (signal === "NEUTRAL") {
        signalElement.innerText = "— NEUTRAL";
    }
    else {
        signalElement.innerText = "WAIT";
    }

    analysisElement.innerText = reason || "";
}


function addChat(message) {

    const item = document.createElement("div");

    item.className = "message";

    const time = new Date()
        .toLocaleTimeString();

    item.innerHTML =
        `<span>${time}</span>${escapeHtml(message)}`;

    messagesElement.appendChild(item);

    messagesElement.scrollTop =
        messagesElement.scrollHeight;

    while (messagesElement.children.length > 100) {
        messagesElement.removeChild(
            messagesElement.firstChild
        );
    }
}


function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}


socket.on("connect", () => {

    connectionElement.innerText =
        "● LIVE";

    connectionElement.className =
        "live";

    addChat("Bot connected to live market stream.");
});


socket.on("disconnect", () => {

    connectionElement.innerText =
        "● OFFLINE";

    connectionElement.className =
        "offline";
});


socket.on("market_data", data => {

    symbolElement.innerText =
        data.symbol;

    marketSelect.value =
        data.symbol;

    updateChart(data.candles);

    updateSignal(
        data.signal,
        data.reason
    );
});


socket.on("trading_chat", data => {
    addChat(data.message);
});


marketSelect.addEventListener(
    "change",
    async () => {

        const symbol =
            marketSelect.value;

        try {

            addChat(
                `Changing market to ${symbol}...`
            );

            const response =
                await fetch("/select", {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        symbol
                    })
                });

            const result =
                await response.json();

            if (!result.ok) {
                addChat(
                    "Market change failed."
                );
            }

        } catch (error) {

            addChat(
                "Connection error while changing market."
            );
        }
    }
);
