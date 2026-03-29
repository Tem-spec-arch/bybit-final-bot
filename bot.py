import os
import pandas as pd
import ta
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta

# --- 1. SETTINGS & PROXY ---
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
# This pulls the proxy from your GitHub Secrets
PROXY_URL = os.getenv("BYBIT_PROXY") 

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
RISK_USD = 10.0          
KILL_SWITCH = 60.0       
RR_RATIO = 4             
MAX_DAILY_TRADES = 4     

# Create Session with Proxy to bypass the 403 Forbidden Error
session = HTTP(
    testnet=False, 
    api_key=API_KEY, 
    api_secret=API_SECRET,
    proxy=PROXY_URL
)

def get_trade_count():
    start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    try:
        res = session.get_executions(category="linear", startTime=start_time)
        return len(set([t['orderId'] for t in res['result']['list']]))
    except: return 0

def run_trading_logic():
    print(f"--- ICT Bot Scan (Proxy Active): {datetime.now().strftime('%H:%M')} ---")
    
    try:
        # Check Balance & Safety
        bal_data = session.get_wallet_balance(accountType="UNIFIED")
        curr_bal = float(bal_data['result']['list'][0]['coin'][0]['walletBalance'])
        print(f"Current Balance: ${curr_bal}")
        
        if curr_bal <= KILL_SWITCH:
            print("DRAWDOWN LIMIT REACHED. Stopping.")
            return
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    for symbol in SYMBOLS:
        # Fetch Data (5m and 1h)
        k5 = session.get_kline(category="linear", symbol=symbol, interval="5", limit=100)
        k1h = session.get_kline(category="linear", symbol=symbol, interval="60", limit=50)
        
        df = pd.DataFrame(k5['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn']).astype(float).iloc[::-1].reset_index(drop=True)
        df1h = pd.DataFrame(k1h['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn']).astype(float).iloc[::-1].reset_index(drop=True)

        # 1. NEWS FILTER (Skip if candle > 1.5%)
        candle_pct = abs(df['Close'].iloc[-1] - df['Open'].iloc[-1]) / df['Open'].iloc[-1]
        if candle_pct > 0.015: continue 

        # 2. ICT COMPONENTS (EMA + Asia Range)
        ema50_1h = ta.trend.EMAIndicator(df1h['Close'], 50).ema_indicator().iloc[-1]
        asia_high, asia_low = df.iloc[:72]['High'].max(), df.iloc[:72]['Low'].min()
        
        curr_p = df['Close'].iloc[-1]
        vol_spike = df['Vol'].iloc[-1] > (df['Vol'].rolling(20).mean().iloc[-1] * 1.8)

        # 3. MSS & FVG LOGIC
        fvg_up = df['Low'].iloc[-1] > df['High'].iloc[-3]
        fvg_down = df['High'].iloc[-1] < df['Low'].iloc[-3]
        mss_buy = curr_p > df['High'].iloc[-2]
        mss_sell = curr_p < df['Low'].iloc[-2]

        # BUY: Discount Sweep + Trend + MSS + FVG
        if curr_p > ema50_1h and curr_p < asia_low and vol_spike and mss_buy and fvg_up:
            execute_order(symbol, "Buy", curr_p, df['Low'].iloc[-2])

        # SELL: Premium Sweep + Trend + MSS + FVG
        elif curr_p < ema50_1h and curr_p > asia_high and vol_spike and mss_sell and fvg_down:
            execute_order(symbol, "Sell", curr_p, df['High'].iloc[-2])

def execute_order(symbol, side, price, stop):
    dist = abs(price - stop)
    if dist > 0:
        qty = round(RISK_USD / dist, 3 if "BTC" in symbol else 2)
        tp = round(price + (dist * RR_RATIO), 2) if side == "Buy" else round(price - (dist * RR_RATIO), 2)
        sl = round(stop, 2)
        try:
            session.place_order(category="linear", symbol=symbol, side=side, orderType="Market", 
                               qty=str(qty), takeProfit=str(tp), stopLoss=str(sl), tpslMode="Full")
            print(f"!!! {side.upper()} {symbol} SUCCESS !!!")
        except Exception as e:
            print(f"Order Error: {e}")

if __name__ == "__main__":
    run_trading_logic()