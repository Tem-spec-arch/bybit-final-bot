import os
import pandas as pd
import ta
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta

# --- 1. FULL ICT CONFIGURATION ---
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LEVERAGE = 66
RISK_USD = 10.0          # Safe $10 Risk
KILL_SWITCH = 60.0       # Stop if account hits $60
RR_RATIO = 4             # 1:4 Reward
MAX_DAILY_TRADES = 4     

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

def run_trading_logic():
    print(f"--- Safe Bot Active: {datetime.now().strftime('%H:%M')} ---")
    
    # Check Balance
    bal_data = session.get_wallet_balance(accountType="UNIFIED")
    curr_bal = float(bal_data['result']['list'][0]['coin'][0]['walletBalance'])
    if curr_bal <= KILL_SWITCH: return

    for symbol in SYMBOLS:
        # Fetch Data
        k5 = session.get_kline(category="linear", symbol=symbol, interval="5", limit=100)
        k1h = session.get_kline(category="linear", symbol=symbol, interval="60", limit=50)
        
        df = pd.DataFrame(k5['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn']).astype(float).iloc[::-1].reset_index(drop=True)
        df1h = pd.DataFrame(k1h['result']['list'], columns=['Time','Open','High','Low','Close','Vol','Turn']).astype(float).iloc[::-1].reset_index(drop=True)

        # A. NEWS FILTER (Candle > 1.5%)
        if (abs(df['Close'].iloc[-1] - df['Open'].iloc[-1]) / df['Open'].iloc[-1]) > 0.015: continue

        # B. ICT COMPONENTS (EMA, Asia Range)
        ema50_1h = ta.trend.EMAIndicator(df1h['Close'], 50).ema_indicator().iloc[-1]
        asia_high, asia_low = df.iloc[:72]['High'].max(), df.iloc[:72]['Low'].min()
        
        curr_price = df['Close'].iloc[-1]
        vol_spike = df['Vol'].iloc[-1] > (df['Vol'].rolling(20).mean().iloc[-1] * 1.8)

        # C. MSS & FVG CHECK
        # MSS: Price breaks previous candle high/low
        # FVG: Gap between Candle 1 and Candle 3
        fvg_up = df['Low'].iloc[-1] > df['High'].iloc[-3]
        fvg_down = df['High'].iloc[-1] < df['Low'].iloc[-3]

        # SELL: Above Asia High + Bearish Bias + MSS + FVG
        if curr_price < ema50_1h and curr_price > asia_high and vol_spike:
            if curr_price < df['Low'].iloc[-2] and fvg_down:
                execute_order(symbol, "Sell", curr_price, df['High'].iloc[-2])

        # BUY: Below Asia Low + Bullish Bias + MSS + FVG
        elif curr_price > ema50_1h and curr_price < asia_low and vol_spike:
            if curr_price > df['High'].iloc[-2] and fvg_up:
                execute_order(symbol, "Buy", curr_price, df['Low'].iloc[-2])

def execute_order(symbol, side, price, stop):
    dist = abs(price - stop)
    if dist > 0:
        qty = RISK_USD / dist
        tp = price + (dist * RR_RATIO) if side == "Buy" else price - (dist * RR_RATIO)
        session.place_order(category="linear", symbol=symbol, side=side, orderType="Market",
                           qty=str(round(qty, 3)), takeProfit=str(round(tp, 2)), 
                           stopLoss=str(round(stop, 2)), tpslMode="Full")

if __name__ == "__main__":
    run_trading_logic()