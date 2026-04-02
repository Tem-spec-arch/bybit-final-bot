import os
import pandas as pd
import ta
from datetime import datetime, timedelta
from pybit.unified_trading import HTTP

PAIRS = ["BTCUSDT", "ETHUSDT"]
RISK = 0.05
MAX_DD = 0.40
MAX_TRADES = 2

session = HTTP(
    testnet=False,
    api_key="YOUR_API_KEY",
    api_secret="YOUR_SECRET"
)

start_balance = None
trades_today = 0

# ================= TIME FILTER =================
def in_session():
    now = datetime.utcnow() + timedelta(hours=1)
    h, m = now.hour, now.minute

    london = ((h == 7 and m >= 30) or (8 <= h < 10) or (h == 10 and m == 0))
    newyork = ((h == 13 and m >= 30) or (14 <= h < 15) or (h == 15 and m <= 30))

    return london or newyork

# ================= HELPERS =================
def get_balance():
    return float(session.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]["totalEquity"])

def get_data(symbol, interval):
    df = pd.DataFrame(session.get_kline(category="linear", symbol=symbol, interval=interval, limit=200)["result"]["list"])
    df.columns = ["time","open","high","low","close","volume","turnover"]
    return df.astype(float)

def get_qty_precision(symbol):
    try:
        info = session.get_instruments_info(category="linear", symbol=symbol)
        step = float(info["result"]["list"][0]["lotSizeFilter"]["qtyStep"])
        return len(str(step).split(".")[1]) if "." in str(step) else 0
    except:
        return 3  # fallback

# ================= STRATEGY =================
def ema_bias(df):
    df["ema50"] = ta.trend.ema_indicator(df["close"], 50)
    return "buy" if df["close"].iloc[-1] > df["ema50"].iloc[-1] else "sell"

def asia(df):
    r = df.tail(72)
    return r["high"].max(), r["low"].min()

def sweep(df, high, low):
    last = df.iloc[-1]
    if last["high"] > high: return "sell"
    if last["low"] < low: return "buy"
    return None

def swings(df):
    highs, lows = [], []
    for i in range(2, len(df)-2):
        if df["high"][i] > df["high"][i-1] and df["high"][i] > df["high"][i+1]:
            highs.append(df["high"][i])
        if df["low"][i] < df["low"][i-1] and df["low"][i] < df["low"][i+1]:
            lows.append(df["low"][i])
    return highs, lows

def mss(df, d):
    highs, lows = swings(df)
    if d == "buy" and highs:
        return df["close"].iloc[-1] > highs[-1]
    if d == "sell" and lows:
        return df["close"].iloc[-1] < lows[-1]
    return False

def fvg(df, d):
    for i in range(len(df)-3, 0, -1):
        c1, c3 = df.iloc[i], df.iloc[i+2]
        if d == "buy" and c1["high"] < c3["low"]:
            return (c1["high"], c3["low"])
        if d == "sell" and c1["low"] > c3["high"]:
            return (c3["high"], c1["low"])
    return None

def in_fvg(price, zone):
    if not zone: return False
    return zone[0] <= price <= zone[1]

# ================= POSITION =================
def position_size(balance, entry, sl):
    dist = abs(entry - sl)
    if dist == 0:
        return None
    return (balance * RISK) / dist

# ================= EXECUTION =================
def place(symbol, side, qty, sl, tp):
    precision = get_qty_precision(symbol)
    qty = round(qty, precision)

    try:
        session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            stopLoss=round(sl, 2),
            takeProfit=round(tp, 2)
        )
    except Exception as e:
        print(f"Order failed: {e}")

# ================= MAIN =================
def run():
    global trades_today, start_balance

    if not in_session():
        return

    bal = get_balance()

    if start_balance is None:
        start_balance = bal

    if bal <= start_balance * (1 - MAX_DD):
        return

    if trades_today >= MAX_TRADES:
        return

    for pair in PAIRS:
        df5 = get_data(pair, "5")
        df1h = get_data(pair, "60")

        bias = ema_bias(df1h)
        high, low = asia(df5)
        sw = sweep(df5, high, low)

        if sw != bias:
            continue

        if not mss(df5, sw):
            continue

        zone = fvg(df5, sw)
        if not zone:
            continue

        price = df5["close"].iloc[-1]
        if not in_fvg(price, zone):
            continue

        entry = price
        sl = high * 1.001 if sw == "sell" else low * 0.999

        risk_dist = abs(entry - sl)

        # ===== RR FIXED TO 1:2 =====
        tp = entry - (risk_dist * 2) if sw == "sell" else entry + (risk_dist * 2)

        qty = position_size(bal, entry, sl)
        if not qty:
            continue

        place(pair, "Sell" if sw == "sell" else "Buy", qty, sl, tp)

        trades_today += 1

if __name__ == "__main__":
    run()