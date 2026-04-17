import ccxt, telebot, os, pandas as pd

# 基础连接
bot = telebot.TeleBot(os.getenv('TG_TOKEN'))
exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASS'),
    'enableRateLimit': True
})

# 查余额
@bot.message_handler(commands=['balance'])
def send_balance(message):
    try:
        bal = exchange.fetch_balance()
        usdt = bal['total'].get('USDT', 0)
        bot.reply_to(message, f"💰 余额: {usdt} USDT")
    except Exception as e:
        bot.reply_to(message, f"❌ 错误: {str(e)}")

# 双龙趋势检查
@bot.message_handler(commands=['check'])
def check_trend(message):
    try:
        symbol = message.text.split()[1].upper()
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
        ema20, ema50 = df['c'].ewm(span=20).mean().iloc[-1], df['c'].ewm(span=50).mean().iloc[-1]
        status = "🐉 双龙抬头" if ema20 > ema50 else "☁️ 震荡"
        bot.reply_to(message, f"📊 {symbol}\n趋势: {status}\n价格: {df['c'].iloc[-1]}")
    except:
        bot.reply_to(message, "用法: /check BTC/USDT")

bot.infinity_polling()
