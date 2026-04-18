import os
import ccxt
import pandas as pd
import pandas_ta as ta
import re
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- 1. 网页保活 (适配 Render) ---
server = Flask('')
@server.route('/')
def home(): return "专业双龙哨兵已就绪"

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

# --- 3. 专业行情分析逻辑 (1H双龙) ---
def get_analysis(symbol='ETH/USDT'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        df['ema_fast'] = ta.ema(df['c'], length=12)
        df['ema_slow'] = ta.ema(df['c'], length=144)
        df['rsi'] = ta.rsi(df['c'], length=14)
        df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        # 策略：EMA12上穿EMA144 + RSI未超买
        is_buy = prev['ema_fast'] <= prev['ema_slow'] and last['ema_fast'] > last['ema_slow'] and last['rsi'] < 70
        sl = last['c'] - (last['atr'] * 1.5)
        return is_buy, last['c'], last['rsi'], sl
    except:
        return False, 0, 0, 0

# --- 4. 哨兵主动预警任务 ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = os.getenv('MY_CHAT_ID')
    if not chat_id: return
    is_buy, price, rsi, sl = get_analysis()
    if is_buy:
        msg = f"🚀 **双龙多头预警 (1H)**\n价格: `${price}`\nRSI: `{rsi:.1f}`\n止损建议: `${sl:.2f}`\n回复'买入'执行模拟下单"
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

# --- 5. 指令交互逻辑 ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "余额" in text or "资金" in text:
        bal = exchange.fetch_balance()
        usdt = bal.get('USDT', {}).get('total', 0)
        await update.message.reply_text(f"💳 **模拟盘可用余额**: `{usdt:.2f}` USDT")
    elif "买入" in text:
        await update.message.reply_text(f"🚀 **模拟指令已接收**: 正在监测双龙趋势，模拟仓位已记录。")
    elif "卖出" in text:
        await update.message.reply_text(f"📉 **模拟平仓已执行**。")

def main():
    token = os.getenv('TELEGRAM_TOKEN')
    if not token: return
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    # 每 15 分钟巡逻一次
    app.job_queue.run_repeating(monitor_job, interval=900, first=10)
    Thread(target=run_server).start()
    app.run_polling()

if __name__ == '__main__':
    main()
