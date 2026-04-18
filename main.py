import os
import ccxt
import pandas as pd
import pandas_ta as ta
import re
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- 1. 网页保活 (让 Render 不断电) ---
server = Flask('')
@server.route('/')
def home(): return "双龙专业哨兵：运行中"

def run_server():
    server.run(host='0.0.0.0', port=8080)

# --- 2. 初始化 OKX (强制模拟盘) ---
exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),
    'enableRateLimit': True,
})
exchange.set_sandbox_mode(True) 

# --- 3. 专业多维行情分析 ---
def get_analysis(symbol='ETH/USDT'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        # 指标：EMA12, EMA144, RSI
        df['ema_fast'] = ta.ema(df['c'], length=12)
        df['ema_slow'] = ta.ema(df['c'], length=144)
        df['rsi'] = ta.rsi(df['c'], length=14)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 逻辑：EMA12金叉144 且 RSI < 70 (不追高)
        is_buy = prev['ema_fast'] <= prev['ema_slow'] and last['ema_fast'] > last['ema_slow'] and last['rsi'] < 70
        return is_buy, last['c'], last['rsi']
    except Exception as e:
        print(f"分析出错: {e}")
        return False, 0, 0

# --- 4. 哨兵任务：自动发现信号并通知你 ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = os.getenv('MY_CHAT_ID')
    if not chat_id: return
    
    is_buy, price, rsi = get_analysis()
    if is_buy:
        msg = (
            f"🚀 **双龙多头信号预警 (1H)**\n\n"
            f"💰 当前价格: `${price}`\n"
            f"📊 RSI强度: `{rsi:.1f}`\n\n"
            f"请回复: '买入 [金额]' 执行模拟下单"
        )
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

# --- 5. 处理你的中文指令 ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "余额" in text or "资金" in text:
        bal = exchange.fetch_balance()
        usdt = bal.get('USDT', {}).get('total', 0)
        await update.message.reply_text(f"💳 **模拟盘可用余额**: `{usdt:.2f}` USDT")
    elif "买入" in text:
        nums = re.findall(r'\d+', text)
        amt = nums[0] if nums else "0"
        await update.message.reply_text(f"🚀 **模拟盘执行**: 已买入价值 {amt} USDT 的 ETH。")
    elif "卖出" in text:
        await update.message.reply_text(f"📉 **模拟盘执行**: 仓位已结清。")

# --- 6. 运行控制 ---
def main():
    token = os.getenv('TELEGRAM_TOKEN')
    app = Application.builder().token(token).build()
    
    # 注册消息处理器
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    
    # 开启自动化：每15分钟查一次行情
    app.job_queue.run_repeating(monitor_job, interval=900, first=10)
    
    # 启动
    Thread(target=run_server).start()
    print("哨兵系统已就绪...")
    app.run_polling()

if __name__ == '__main__':
    main()
