import os
import pandas as pd
import ta
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta

# --- CONFIG ---
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LEVERAGE = 66
RISK_PCT = 0.10          # $10 RISK PER TRADE
STARTING_BALANCE = 100.0 
DRAWDOWN_LIMIT = 0.40    # Kill-switch if balance drops to $60
MAX_TRADES_PER_SYMBOL_24H = 4 
RR = 4           

session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

def get_trade_count(symbol):
    start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    try:
        res = session.get_executions(category="linear", symbol=symbol, startTime=start_time)
        return len(set([t['orderId'] for t in res['result']['list']]))
    except: return 0

def run_bot():
    print(f"--- $10 Bot Scan: {datetime.now().strftime('%H:%M')} ---")
    bal_res = session.get_wallet_balance(accountType="UNIFIED")
    current_bal = float(bal_res['result']['list'][0]['coin'][0]['walletBalance'])
    
    if current_bal < (STARTING_BALANCE * (1 - DRAWDOWN_LIMIT)):
        print(f"SAFETY STOP: Balance ${current_bal} is too low.")
        return

    for symbol in SYMBOLS:
        if get_trade_count(symbol) >= MAX_TRADES_PER_SYMBOL_24H: continue

        k5 = session.get_kline(category="linear", symbol=symbol, interval="5", limit=100)
        k1h = session.get_kline(category="linear", symbol=symbol, interval="60", limit=50)
        df = pd.DataFrame(k5['result']['list']).astype({'High':float,'Low':float,'Close':float,'Open':float,'Volume':float}).iloc[::-1].reset_index(drop=True)
        df1h = pd.DataFrame(k1h['result']['list']).astype({'Close':float}).iloc[::-1].reset_index(drop=True)

        # NEWS FILTER: If candle move > 1.5%, skip
        if (abs(df['Close'].iloc[-1] - df['Open'].iloc[-1]) / df['Open'].iloc[-1]) > 0.015:
            print(f"News Alert: Skipping {symbol} due to extreme candle size.")
            continue

        ema50_1h = ta.trend.EMAIndicator(df1h['Close'], 50).ema_indicator().iloc[-1]
        a_high, a_low = df.iloc[:72]['High'].max(), df.iloc[:72]['Low'].min()
        price, vol = df['Close'].iloc[-1], df['Volume'].iloc[-1]
        vol_spike = vol > (df['Volume'].rolling(20).mean().iloc[-1] * 1.8)

        # SELL
        if price < ema50_1h and price > a_high and vol_spike and price < df['Low'].iloc[-6]:
            place_trade(symbol, "Sell", price, df['High'].iloc[-6], current_bal * RISK_PCT)
        # BUY
        elif price > ema50_1h and price < a_low and vol_spike and price > df['High'].iloc[-6]:
            place_trade(symbol, "Buy", price, df['Low'].iloc[-6], current_bal * RISK_PCT)

def place_trade(symbol, side, price, stop, risk):
    dist = abs(price - stop)
    if dist > 0:
        qty = risk / dist
        tp = price + (dist * RR) if side == "Buy" else price - (dist * RR)
        session.place_order(category="linear", symbol=symbol, side=side, orderType="Market", 
                           qty=str(round(qty,3)), takeProfit=str(round(tp,2)), stopLoss=str(round(stop,2)), tpslMode="Full")
        print(f"TRADE PLACED: {side} {symbol}")

if __name__ == "__main__":
    run_bot()