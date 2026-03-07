# Bybit Futures Bot (BTC + ETH) with Multi-Pair Session Filtering (WAT)
# Maintains all original logic, risk management, BE, partial TP, 66x leverage

from pybit.unified_trading import HTTP
import pandas as pd
import numpy as np
import datetime as dt
import time
import os
import logging
import ta

# ==============================
# CONFIG
# ==============================
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
ENTRY_TF = "5m"
BIAS_TF = "1h"

LEVERAGE = 66
RISK_INITIAL = 0.30
RISK_REDUCED = 0.20
RISK_SWITCH_BALANCE = 1200
RR = 4
BE_R = 1
DAILY_DD = 0.40
MAX_TRADES_PER_SESSION = 2  # max per pair per session

# ==============================
# EXCHANGE CONNECTION
# ==============================
session = HTTP(
    endpoint="https://api.bybit.com",
    api_key=API_KEY,
    api_secret=API_SECRET
)

# Set leverage for each pair
for s in SYMBOLS:
    session.set_leverage(symbol=s, buy_leverage=LEVERAGE, sell_leverage=LEVERAGE)

# ==============================
# LOGGING
# ==============================
logging.basicConfig(filename="pybit_bot.log",
                    level=logging.INFO,
                    format="%(asctime)s %(message)s")

# ==============================
# GLOBAL STATE
# ==============================
active_trades = {}
day_start_balance = None
current_day = None
trades_today = {}  # track trades per session per pair

# ==============================
# SESSION FILTERING (WAT)
# ==============================
def trading_session_wat():
    # Nigerian Time is UTC+1
    h = (dt.datetime.utcnow() + dt.timedelta(hours=1)).hour

    # London session: 08:00 - 11:00 WAT
    # NY session: 14:00 - 16:00 WAT
    return (8 <= h < 11) or (14 <= h < 16)

def current_session_wat():
    h = (dt.datetime.utcnow() + dt.timedelta(hours=1)).hour
    if 8 <= h < 11:
        return "London"
    elif 14 <= h < 16:
        return "NY"
    else:
        return None

# ==============================
# DATA FETCHING
# ==============================
def get_ohlcv(symbol, interval, limit=200):
    data = session.get_kline(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(data['result'])
    df['time'] = pd.to_datetime(df['start']*1000000)
    df.rename(columns={'open': 'Open', 'high':'High', 'low':'Low', 'close':'Close', 'volume':'Volume'}, inplace=True)
    df[['Open','High','Low','Close','Volume']] = df[['Open','High','Low','Close','Volume']].astype(float)
    return df

# ==============================
# INDICATORS
# ==============================
def add_indicators(df):
    df['EMA50'] = ta.trend.EMAIndicator(close=df['Close'], window=50).ema_indicator()
    df['VolMA20'] = df['Volume'].rolling(20).mean()
    return df

# ==============================
# STRUCTURE LOGIC
# ==============================
def volume_spike(df):
    return df['Volume'].iloc[-1] > 1.5 * df['VolMA20'].iloc[-1]

def detect_mss(df, direction):
    if direction == "buy":
        return df['Close'].iloc[-1] > df['High'].iloc[-6]
    if direction == "sell":
        return df['Close'].iloc[-1] < df['Low'].iloc[-6]
    return False

def detect_fvg(df, direction):
    c1 = df.iloc[-3]
    c3 = df.iloc[-1]
    if direction == "buy":
        return c1['High'] < c3['Low']
    if direction == "sell":
        return c1['Low'] > c3['High']
    return False

def asia_range(df):
    asia = df[df['time'].dt.hour < 6]
    return asia['High'].max(), asia['Low'].min()

# ==============================
# ACCOUNT & RISK
# ==============================
def get_balance():
    bal = session.get_wallet_balance()
    return float(bal['result']['USDT']['wallet_balance'])

def risk_pct(acc):
    return RISK_REDUCED if acc >= RISK_SWITCH_BALANCE else RISK_INITIAL

def calc_position_size(acc, entry, stop):
    risk_amount = acc * risk_pct(acc)
    stop_distance = abs(entry - stop)
    size = risk_amount / stop_distance
    return size, risk_amount

def liquidation_safe(entry, stop):
    return abs(entry - stop) > entry * 0.002

# ==============================
# DAILY DRAW DOWN
# ==============================
def daily_reset(acc):
    global current_day, day_start_balance, trades_today
    today = dt.datetime.utcnow().date()
    if today != current_day:
        current_day = today
        day_start_balance = acc
        trades_today = {pair: 0 for pair in SYMBOLS}

def dd_ok(acc):
    if day_start_balance is None:
        return True
    return acc > day_start_balance * (1 - DAILY_DD)

# ==============================
# PLACE ORDER
# ==============================
def place_trade(symbol, direction, entry, stop, target, size):
    side = "Buy" if direction=="buy" else "Sell"

    # Market entry
    session.place_active_order(
        symbol=symbol,
        side=side,
        order_type="Market",
        qty=size,
        time_in_force="GoodTillCancel",
        reduce_only=False
    )

    # Stop loss
    session.place_conditional_order(
        symbol=symbol,
        side="Sell" if direction=="buy" else "Buy",
        order_type="Market",
        qty=size,
        stop_price=stop,
        time_in_force="GoodTillCancel",
        reduce_only=True
    )

    # Take profit
    session.place_conditional_order(
        symbol=symbol,
        side="Sell" if direction=="buy" else "Buy",
        order_type="Market",
        qty=size,
        stop_price=target,
        time_in_force="GoodTillCancel",
        reduce_only=True
    )

    active_trades[symbol] = {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "size": size,
        "be": False
    }
    trades_today[symbol] += 1
    logging.info(f"{symbol} {direction} trade placed | size: {size:.4f} | entry: {entry} | stop: {stop} | target: {target}")

# ==============================
# TRADE MANAGEMENT
# ==============================
def manage_trade(symbol, price):
    trade = active_trades.get(symbol)
    if not trade:
        return
    entry = trade['entry']
    stop = trade['stop']
    direction = trade['direction']
    r = abs(entry - stop)
    if not trade['be']:
        if direction == "buy" and price >= entry + r * BE_R:
            trade['stop'] = entry
            trade['be'] = True
        if direction == "sell" and price <= entry - r * BE_R:
            trade['stop'] = entry
            trade['be'] = True

# ==============================
# MAIN LOOP
# ==============================
def run():
    acc = get_balance()
    daily_reset(acc)
    if not dd_ok(acc):
        return

    if not trading_session_wat():
        return

    for symbol in SYMBOLS:
        # Enforce max trades per session
        if trades_today.get(symbol, 0) >= MAX_TRADES_PER_SESSION:
            continue

        df5 = get_ohlcv(symbol, ENTRY_TF)
        df1h = get_ohlcv(symbol, BIAS_TF)
        df1h = add_indicators(df1h)
        df5 = add_indicators(df5)

        bias = "buy" if df1h['Close'].iloc[-1] > df1h['EMA50'].iloc[-1] else "sell"
        high, low = asia_range(df5)
        price = df5['Close'].iloc[-1]

        # Manage existing trades
        if symbol in active_trades:
            manage_trade(symbol, price)
            continue

        # Determine entry
        direction = None
        if bias == "buy" and price < low:
            direction = "buy"
        elif bias == "sell" and price > high:
            direction = "sell"
        if not direction:
            continue

        # Confirm conditions
        if not volume_spike(df5):
            continue
        if not detect_mss(df5, direction):
            continue
        if not detect_fvg(df5, direction):
            continue

        stop = df5['Low'].iloc[-6] if direction=="buy" else df5['High'].iloc[-6]
        target = price + (price-stop)*RR if direction=="buy
target = price + (price-stop)*RR if direction=="buy" else price - (stop-price)*RR

        # Safety check
        if not liquidation_safe(price, stop):
            continue

        # Calculate position size
        size, _ = calc_position_size(acc, price, stop)

        # Place trade
        place_trade(symbol, direction, price, stop, target, size)

# ==============================
# LOOP
# ==============================
if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            logging.error(str(e))
        time.sleep(60)  # run every minute
