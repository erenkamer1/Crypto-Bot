import requests
import config

def send_message(message):
    """Send plain text message."""
    if not config.TELEGRAM_TOKEN or config.TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN":
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram send failed: {e}")

def send_signal(signal_type, data, symbol, sl, tp1, tp2, order_result=None):
    """
    Send signal details.
    order_result: Binance response when a live order was placed.
    """
    emo = "🟢" if "LONG" in signal_type else "🔴"
    price = data['close']
    stop_loss = sl

    if order_result:
        trade_status = f"✅ **LIVE ORDER OPENED** (Binance)\n📝 Order ID: {order_result.get('id', 'N/A')}"
    else:
        trade_status = "📋 Test mode (simulation)"

    msg = f"""
{emo} **{signal_type}**
#{symbol.replace('/','').replace(':USDT','')}

💰 **Entry:** {price}
🛑 **Stop loss:** {stop_loss:.4f}
🎯 **TP1:** {tp1:.4f}
🚀 **TP2:** {tp2:.4f}

{trade_status}

📊 **Indicators:**
WT1: {data['WT_1']:.2f}
ADX: {data['ADX']:.2f}
    """
    send_message(msg)

def send_trade_update(symbol, event_type, price, profit_pct, is_closed):
    """Trade update (TP/SL)."""
    emo = ""
    title = ""

    if event_type == "TP1":
        emo = "✅"
        title = "TP1 HIT"
    elif event_type == "TP2":
        emo = "🚀"
        title = "TP2 HIT"
    elif event_type == "SL":
        emo = "🛑"
        title = "STOP LOSS"

    status_msg = "Trade closed" if is_closed else "Trade open (SL moved to breakeven)"

    msg = f"""
{emo} **{title}** - #{symbol.replace('/','')}

💲 **Price:** {price}
📈 **P&L:** %{profit_pct*100:.2f}
ℹ️ {status_msg}
    """
    send_message(msg)

def check_commands():
    """Poll user commands (/excel, /excelai, etc.)."""
    try:
        import telegram_commands
        return telegram_commands.check_for_commands()
    except Exception as e:
        print(f"Command check error: {e}")
        return False
