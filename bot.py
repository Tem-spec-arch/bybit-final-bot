import os
import pandas as pd
import ta
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta

# --- 1. SETTINGS ---
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LEVERAGE = 66
RISK_USD = 10.0          # Fixed $10 Risk
STARTING_BAL = 100.0     
KILL_SWITCH = 60.0       # Stop if account hits $60
RR_RATIO = 4             # 1:4 Reward
MAX_DAILY_TRADES = 4     # Total trades allowed per day

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

def get_trade_count():
    """Checks Bybit for how many trades happened in the last 24h"""
    start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    try:
        res = session.get_executions(category="linear", startTime=start_time)
        return len(set([t['orderId'] for t in res['result']['list']]))
    except: return 0

def run_trading_logic():
    print(f"--- Safe Bot Scanning: {datetime.now().strftime('%Y-%m-%d %H:%M')} ---")
    
    # Check Balance & Daily Limit
    bal_data = session.get_wallet_balance(accountType="UNIFIED")
    curr_bal = float(bal_data['result']['list'][0]['coin'][0]['walletBalance'])
    
    if curr_bal <= KILL_SWITCH:
        print(f"STOP: Balance ${curr_bal} is at/below safety limit ($60).")
        return

    if get_trade_count() >= MAX_DAILY_TRADES:
        print("Daily trade limit reached. Waiting for tomorrow.")
        return

    for symbol in SYMBOLS:
        # Fetch 5m (for entries) and 1h (for trend)
        k5 = session.get_kline(category="linear", symbol=symbol, interval="5", limit=100)
        k1h = session.get_kline(category="linear", symbol=symbol, interval="60", limit=50)
        
        df = pd.DataFrame(k5['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn'])
        df = df.astype(float).iloc[::-1].reset_index(drop=True)
        
        df1h = pd.DataFrame(k1h['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn'])
        df1h = df1h.astype(float).iloc[::-1].reset_index(drop=True)

        # 2. NEWS/VOLATILITY FILTER
        # Check if the last 5m candle is a "War Spike" (> 1.5% move)
        candle_pct = abs(df['Close'].iloc[-1] - df['Open'].iloc[-1]) / df['Open'].iloc[-1]
        if candle_pct > 0.015:
            print(f"ALERT: Extreme volatility on {symbol}. Skipping for safety.")
            continue

        # 3. TECHNICAL INDICATORS
        ema50_1h = ta.trend.EMAIndicator(df1h['Close'], 50).ema_indicator().iloc[-1]
        asia_high = df.iloc[:72]['High'].max() # Asia Range (Approx first 6 hours)
        asia_low = df.iloc[:72]['Low'].min()
        
        curr_price = df['Close'].iloc[-1]
        avg_vol = df['Vol'].rolling(20).mean().iloc[-1]
        vol_spike = df['Vol'].iloc[-1] > (avg_vol * 1.8)

        # 4. ENTRY LOGIC (Sweep + Vol + MSS)
        # SELL: Price above Asia High + Vol Spike + MSS (Break below previous 5m low)
        if curr_price < ema50_1h and curr_price > asia_high and vol_spike:
            if curr_price < df['Low'].iloc[-2]: # Market Structure Shift
                execute_order(symbol, "Sell", curr_price, df['High'].iloc[-2])

        # BUY: Price below Asia Low + Vol Spike + MSS (Break above previous 5m high)
        elif curr_price > ema50_1h and curr_price < asia_low and vol_spike:
            if curr_price > df['High'].iloc[-2]:
                execute_order(symbol, "Buy", curr_price, df['Low'].iloc[-2])

def execute_order(symbol, side, price, stop):
    dist = abs(price - stop)
    if dist > 0:
        qty = RISK_USD / dist
        tp = price + (dist * RR_RATIO) if side == "Buy" else price - (dist * RR_RATIO)
        
        session.place_order(
            category="linear", symbol=symbol, side=side, orderType="Market",
            qty=str(round(qty, 3)), takeProfit=str(round(tp, 2)), 
            stopLoss=str(round(stop, 2)), tpslMode="Full"
        )
        print(f"!!! {side.upper()} ORDER PLACED ON {symbol} !!!")

if __name__ == "__main__":
    run_trading_logic()