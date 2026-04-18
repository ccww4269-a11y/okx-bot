import os
import ccxt
import pandas as pd
import re
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- 1. 网页保活 ---
server = Flask('')
@server.route('/')
def home(): return "双龙全自动-追踪止盈版：工作中"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# --- 2. 初始化 OKX ---
exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})
exchange.set_sandbox_mode(True) # 模拟盘，实盘请改为 False

last_signal_time = None

# --- 3. 核心算法 ---
def get_analysis(symbol='ETH/USDT-SWAP'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        df['ema_12'] = df['c'].ewm(span=12, adjust=False).mean()
        df['ema_144'] = df['c'].ewm(span=144, adjust=False).mean()
        last, prev = df.iloc[-1], df.iloc[-2]
        # EMA12 金叉 EMA144
        is_buy = prev['ema_12'] <= prev['ema_144'] and last['ema_12'] > last['ema_144']
        return is_buy, last['c'], last['t']
    except Exception as e:
        print(f"分析失败: {e}"); return False, 0, 0

# --- 4. 【下单执行函数】 ---
async def place_order(chat_id, context, lv=10, amt="1"):
    symbol = 'ETH/USDT-SWAP'
    try:
        # 1. 设置杠杆
        exchange.set_leverage(lv, symbol)
        
        # 2. 获取当前价
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        
        # 3. 市价开多
        order = exchange.create_market_buy_order(symbol, amt, {'tdMode': 'cross'})
        
        # 4. 挂载 10% 移动止盈单 (Trailing Stop)
        # 逻辑：从最高点回撤 10% 自动平仓
        exchange.create_order(
            symbol=symbol,
            type='conditional',
            side='sell',
            amount=amt,
            params={
                'ordType': 'move_order_stop', # 移动止损
                'callbackRatio': '0.1',       # 回撤 10%
                'activePrice': f"{price}",    # 立即激活
                'reduceOnly': True
            }
        )
        
        # 5. 挂载 -10% 硬止损单
        sl_price = price * (1 - 0.1 / lv) # 考虑杠杆后的 10% 本金止损
        exchange.create_order(
            symbol=symbol,
            type='stop',
            side='sell',
            amount=amt,
            params={
                'stopPrice': f"{sl_price:.2f}",
                'reduceOnly': True
            }
        )

        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"✅ **开仓执行成功！**\n价格: `${price}`\n🛡️ 硬止损: `{sl_price:.2f}`\n📈 追踪止盈: `10% 回撤`"
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ 执行失败: {e}")

# --- 5. 自动巡逻任务 ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    global last_signal_time
    chat_id = os.getenv('MY_CHAT_ID')
    is_buy, price, current_time = get_analysis()
    
    if is_buy and current_time != last_signal_time:
        last_signal_time = current_time
        await place_order(chat_id, context)

# --- 6. 中文指令处理器 ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    try:
        if "余额" in text:
            bal = exchange.fetch_balance()
            await update.message.reply_text(f"💳 余额: `{bal.get('USDT', {}).get('total', 0)}` USDT")
        elif "开多" in text:
            params = re.findall(r'\d+', text)
            lv = int(params[0]) if len(params) > 0 else 10
            amt = params[1] if len(params) > 1 else "1"
            await place_order(chat_id, context, lv, amt)
        elif "平仓" in text:
            exchange.create_market_order('ETH/USDT-SWAP', 'sell', 1, {'reduceOnly': True})
            await update.message.reply_text("⚡ 已紧急清仓所有仓位！")
    except Exception as e:
        await update.message.reply_text(f"❌ 操作失败: {e}")

def main():
    token = os.getenv('TELEGRAM_TOKEN')
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    if app.job_queue:
        app.job_queue.run_repeating(monitor_job, interval=900, first=10)
    Thread(target=run_server, daemon=True).start()
    print("🚀 双龙追踪系统已就绪...")
    app.run_polling()

if __name__ == '__main__':
    main()
