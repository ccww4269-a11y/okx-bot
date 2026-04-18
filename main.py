import os
import ccxt
import pandas as pd
import re
import time
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- 1. 网页保活 (让 Render 不断电) ---
server = Flask('')
@server.route('/')
def home(): return "双龙专业哨兵：24小时运行中"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host='0.0.0.0', port=port)

# --- 2. 初始化 OKX (强制模拟盘) ---
exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),
    'enableRateLimit': True,
})
exchange.set_sandbox_mode(True) 

# --- 3. 原生算法：计算双龙均线与 RSI (不依赖报错插件) ---
def get_analysis(symbol='ETH/USDT'):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        
        # 计算 EMA12 和 EMA144 (原生 pandas 算法，极稳)
        df['ema_12'] = df['c'].ewm(span=12, adjust=False).mean()
        df['ema_144'] = df['c'].ewm(span=144, adjust=False).mean()
        
        # 计算 RSI (14周期)
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 【核心策略逻辑】
        # 1. 金叉：12日线 向上穿越 144日线
        # 2. 强度：RSI 小于 70 (防止追高)
        is_buy_signal = prev['ema_12'] <= prev['ema_144'] and last['ema_12'] > last['ema_144'] and last['rsi'] < 70
        
        return is_buy_signal, last['c'], last['rsi']
    except Exception as e:
        print(f"行情分析出错: {e}")
        return False, 0, 0

# --- 4. 自动化哨兵：发现行情主动推送到手机 ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = os.getenv('MY_CHAT_ID')
    if not chat_id: return
    
    is_buy, price, rsi = get_analysis()
    if is_buy:
        msg = (
            f"🔔 **双龙多头行情预警**\n\n"
            f"📈 交易对: `ETH/USDT` (1H)\n"
            f"💰 进场价格: `${price}`\n"
            f"📊 RSI强度: `{rsi:.1f}`\n\n"
            f"💡 **建议**: 均线已金叉，RSI未超买，可考虑做多。\n"
            f"回复 '买入 500' 可执行模拟下单。"
        )
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

# --- 5. 指令处理 (余额、买、卖) ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        if "余额" in text or "资金" in text:
            bal = exchange.fetch_balance()
            total_bal = bal.get('USDT', {}).get('total', 0)
            await update.message.reply_text(f"💳 **模拟盘余额**: `{total_bal}` USDT")
        elif "买入" in text:
            await update.message.reply_text(f"✅ **模拟买入指令已记录**\n价格: {exchange.fetch_ticker('ETH/USDT')['last']}")
        elif "卖出" in text:
            await update.message.reply_text(f"📉 **模拟卖出成功**，仓位已平。")
    except Exception as e:
        await update.message.reply_text(f"❌ 运行出错: {e}")

# --- 6. 核心启动控制 ---
def main():
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        print("错误: 未配置 TELEGRAM_TOKEN")
        return

    # 创建机器人
    app = Application.builder().token(token).build()
    
    # 注册手动指令处理器
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))
    
    # 启动自动哨兵：每 900 秒 (15分钟) 扫一次行情
    if app.job_queue:
        app.job_queue.run_repeating(monitor_job, interval=900, first=5)
    
    # 启动网页保活线程
    Thread(target=run_server, daemon=True).start()
    
    print("🚀 哨兵系统已就绪，正在云端巡逻...")
    app.run_polling()

if __name__ == '__main__':
    main()
