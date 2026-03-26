import time
import ccxt
import config
import trade_manager
from colorama import Fore, Style

MAX_TIMESTAMP_RETRIES = 2
RETRY_DELAY_SEC = 3
MAX_API_RETRIES = 2
MAX_4130_RETRIES = 4
RETRY_4130_DELAY_SEC = 5
FILL_FETCH_DELAY_SEC = 1

try:
    import runtime_config
    RUNTIME_CONFIG_AVAILABLE = True
except ImportError:
    RUNTIME_CONFIG_AVAILABLE = False


def _is_timestamp_error(e):
    """Detect Binance -1021 timestamp error."""
    err_str = str(e)
    return '-1021' in err_str or '1000ms ahead' in err_str or '1000ms behind' in err_str


def _is_transient_api_error(e):
    """Transient API errors (retryable)."""
    err_str = str(e).lower()
    return (
        'exchangeinfo' in err_str or
        'exchange info' in err_str or
        'timeout' in err_str or
        'connection' in err_str or
        'network' in err_str or
        'econnreset' in err_str or
        '502' in err_str or
        '503' in err_str or
        '429' in err_str or
        'ratelimit' in err_str
    )


def _is_unknown_order_error(e):
    """Binance -2011 UNKNOWN_ORDER — order already gone."""
    err_str = str(e)
    return 'Unknown order' in err_str or 'UNKNOWN_ORDER' in err_str or '-2011' in err_str


def fetch_ticker_with_retry(exchange, symbol):
    """fetch_ticker with retry on transient errors."""
    if hasattr(exchange, 'id') and exchange.id == 'binanceusdm':
        symbol = _to_futures_symbol(symbol)
    last_err = None
    for attempt in range(MAX_API_RETRIES + 1):
        try:
            return exchange.fetch_ticker(symbol)
        except Exception as e:
            last_err = e
            if _is_transient_api_error(e) and attempt < MAX_API_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
                continue
            raise
    raise last_err


def _sync_time_before_trade(exchange):
    """Refresh CCXT time offset from Binance server time."""
    try:
        exchange.fetch_time()
    except Exception:
        pass


def _get_fill_price(exchange, order, symbol, side, amount):
    """Average fill price for a market order."""
    avg = order.get('average')
    if avg and float(avg) > 0:
        return float(avg)
    filled = order.get('filled')
    cost = order.get('cost')
    if filled and float(filled) > 0 and cost and float(cost) > 0:
        return float(cost) / float(filled)

    try:
        time.sleep(FILL_FETCH_DELAY_SEC)
        o = exchange.fetch_order(order['id'], symbol)
        avg = o.get('average')
        if avg and float(avg) > 0:
            return float(avg)
        if o.get('filled') and o.get('cost'):
            return float(o['cost']) / float(o['filled'])
    except Exception:
        pass
    return None


def _get_tp_sl_pcts():
    """TP/SL percentages from runtime config."""
    if RUNTIME_CONFIG_AVAILABLE:
        rc = runtime_config.get_config()
        sl_pct = rc.sl_pct / 100.0
        tp1_pct = rc.tp1_pct / 100.0
        tp2_pct = rc.tp2_pct / 100.0
        return sl_pct, tp1_pct, tp2_pct
    return config.STOP_LOSS_PCT, config.TAKE_PROFIT_1_PCT, config.TAKE_PROFIT_2_PCT


def get_exchange(use_runtime_config=True):
    """Create Binance USDT-M futures exchange."""
    api_key = config.API_KEY
    api_secret = config.API_SECRET

    if use_runtime_config and RUNTIME_CONFIG_AVAILABLE:
        rc = runtime_config.get_config()
        if rc.api_key and rc.api_secret:
            api_key = rc.api_key
            api_secret = rc.api_secret

    exchange = ccxt.binanceusdm({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'adjustForTimeDifference': True,
        }
    })

    return exchange


def _to_futures_symbol(symbol):
    """Normalize symbol for binanceusdm (e.g. BTC/USDT -> BTC/USDT:USDT)."""
    if ':' not in symbol and '/USDT' in symbol:
        return f"{symbol}:USDT"
    return symbol


def get_balance(exchange, currency='USDT'):
    """Fetch wallet balance."""
    try:
        balance = exchange.fetch_balance()
        return balance['free'].get(currency, 0.0)
    except Exception as e:
        print(f"Balance fetch failed: {e}")
        return 0.0


def set_leverage(exchange, symbol, leverage=1):
    """Set leverage (futures only)."""
    symbol = _to_futures_symbol(symbol)
    try:
        exchange.load_markets()
        exchange.set_leverage(leverage, symbol)
        print(f"Leverage set: {symbol} -> {leverage}x")
    except Exception as e:
        print(f"Leverage failed ({symbol}): {e}")


def _is_auto_trade_enabled():
    """Check AUTO_TRADE and runtime_config."""
    if not config.AUTO_TRADE:
        return False
    if RUNTIME_CONFIG_AVAILABLE:
        rc = runtime_config.get_config()
        if not rc.auto_trade:
            return False
    return True


def execute_trade(symbol, signal_type, current_price, sl=None, tp1=None, tp2=None):
    """
    Send order and place TP/SL on Binance.
    Returns: { 'order': order, 'amount': amount, 'sl_order_id': ..., 'tp_order_id': ... } or None
    """
    if not _is_auto_trade_enabled():
        return None

    if RUNTIME_CONFIG_AVAILABLE:
        rc = runtime_config.get_config()
        if not rc.allow_new_trades:
            print(f"New trades disabled — skipping: {symbol}")
            return None

    exchange = get_exchange()
    _sync_time_before_trade(exchange)
    symbol = _to_futures_symbol(symbol)

    last_error = None
    for attempt in range(MAX_TIMESTAMP_RETRIES + 1):
        try:
            exchange.load_markets()
            market = exchange.market(symbol)
            quote_currency = market['quote']

            if config.IS_FUTURES:
                set_leverage(exchange, symbol, config.LEVERAGE)

            side = None
            amount = 0

            balance = get_balance(exchange, quote_currency)

            if RUNTIME_CONFIG_AVAILABLE:
                rc = runtime_config.get_config()
                rc.current_balance = balance
                usdt_to_spend = rc.get_trade_amount()
            else:
                if config.TRADE_AMOUNT_TYPE == 'PERCENT':
                    usdt_to_spend = balance * config.TRADE_AMOUNT_VALUE
                else:
                    usdt_to_spend = config.TRADE_AMOUNT_VALUE

            usdt_to_spend = min(usdt_to_spend, balance)

            if usdt_to_spend < 10:
                print(f"Insufficient balance or below min: {usdt_to_spend} USDT")
                return None

            amount = usdt_to_spend / current_price
            amount = exchange.amount_to_precision(symbol, amount)
            amount = float(amount)

            if "LONG" in signal_type:
                side = 'buy'
            elif "SHORT" in signal_type:
                side = 'sell'

            if not config.IS_FUTURES and side == 'sell':
                print("Cannot open short on spot.")
                return None

            if amount > 0:
                print(f"{Fore.RED}LIVE BINANCE - SENDING ORDER ({'FUTURES' if config.IS_FUTURES else 'SPOT'}): {side.upper()} {symbol} Qty: {amount}{Style.RESET_ALL}")
                order = exchange.create_market_order(symbol, side, amount)
                print(f"{Fore.RED}LIVE BINANCE - ORDER FILLED! Order ID: {order['id']}{Style.RESET_ALL}")

                real_entry = _get_fill_price(exchange, order, symbol, side, amount)
                if real_entry and real_entry > 0:
                    sl_pct, tp1_pct, tp2_pct = _get_tp_sl_pcts()
                    if "LONG" in signal_type:
                        sl = real_entry * (1 - sl_pct)
                        tp1 = real_entry * (1 + tp1_pct)
                        tp2 = real_entry * (1 + tp2_pct)
                    else:
                        sl = real_entry * (1 + sl_pct)
                        tp1 = real_entry * (1 - tp1_pct)
                        tp2 = real_entry * (1 - tp2_pct)
                    print(f"{Fore.RED}LIVE BINANCE - Fill price: {real_entry} (signal: {current_price}){Style.RESET_ALL}")
                else:
                    real_entry = current_price

                sl_order_id = None
                tp_order_id = None
                if config.IS_FUTURES and sl and tp2:
                    sl_order_id, tp_order_id = _place_tp_sl_orders(
                        exchange, symbol, signal_type, amount, sl, tp2
                    )

                return {
                    'order': order,
                    'id': order.get('id'),
                    'amount': amount,
                    'real_entry': real_entry,
                    'sl': sl,
                    'tp1': tp1,
                    'tp2': tp2,
                    'sl_order_id': sl_order_id,
                    'tp_order_id': tp_order_id
                }
            return None

        except Exception as e:
            last_error = e
            if _is_timestamp_error(e) and attempt < MAX_TIMESTAMP_RETRIES:
                print(f"Time sync error, {RETRY_DELAY_SEC} s, retrying...")
                time.sleep(RETRY_DELAY_SEC)
                _sync_time_before_trade(exchange)
            else:
                print(f"Trade error: {e}")
                if _is_timestamp_error(e) and attempt >= MAX_TIMESTAMP_RETRIES:
                    print("Sync system clock with internet time")
                return None
    return None


def _place_tp_sl_orders(exchange, symbol, signal_type, amount, sl_price, tp_price):
    """
    Place SL/TP on Binance Futures.
    reduceOnly+amount closes only this trade size.
    Returns: (sl_order_id, tp_order_id)
    """
    close_side = 'sell' if "LONG" in signal_type else 'buy'

    sl_price = float(exchange.price_to_precision(symbol, sl_price))
    tp_price = float(exchange.price_to_precision(symbol, tp_price))

    try:
        sl_buffer = runtime_config.get_config().sl_buffer_pct / 100.0
        if sl_buffer > 0:
            if "LONG" in signal_type:
                sl_price = float(exchange.price_to_precision(symbol, sl_price * (1 + sl_buffer)))
            else:
                sl_price = float(exchange.price_to_precision(symbol, sl_price * (1 - sl_buffer)))
            print(f"SL buffer applied (%{sl_buffer*100:.2f}): Yeni SL = {sl_price}")
    except Exception as e:
        print(f"SL buffer error: {e}")

    base_params = {
        'reduceOnly': True,
        'workingType': 'MARK_PRICE',
        'priceProtect': 'TRUE'
    }

    sl_order_id = None
    tp_order_id = None

    try:
        sl_order = exchange.create_order(
            symbol=symbol,
            type='STOP_MARKET',
            side=close_side,
            amount=amount,
            price=None,
            params={**base_params, 'stopPrice': sl_price}
        )
        sl_order_id = sl_order.get('id')
        print(f"SL order placed (reduceOnly, amount={amount}): {sl_price} | Order ID: {sl_order_id}")
    except Exception as e:
        print(f"SL order failed: {e}")

    try:
        tp_order = exchange.create_order(
            symbol=symbol,
            type='TAKE_PROFIT_MARKET',
            side=close_side,
            amount=amount,
            price=None,
            params={**base_params, 'stopPrice': tp_price}
        )
        tp_order_id = tp_order.get('id')
        print(f"TP order placed (reduceOnly, amount={amount}): {tp_price} | Order ID: {tp_order_id}")
    except Exception as e:
        print(f"TP order failed: {e}")

    return sl_order_id, tp_order_id


def cancel_trade_orders(symbol, sl_order_id, tp_order_id, exchange=None):
    """
    Cancel TP/SL for a specific trade by order id.
    Prefer over cancel_all_orders() so other trades' orders stay intact.
    UNKNOWN_ORDER (-2011) is expected if Binance already removed the order.
    """
    own_exchange = exchange is None
    if own_exchange:
        exchange = get_exchange()
        _sync_time_before_trade(exchange)

    futures_symbol = _to_futures_symbol(symbol)

    for label, oid in [("SL", sl_order_id), ("TP", tp_order_id)]:
        if not oid:
            continue
        try:
            exchange.cancel_order(oid, futures_symbol)
            print(f"{label} order cancelled (ID: {oid})")
        except Exception as e:
            if _is_unknown_order_error(e):
                print(f"{label} order already closed/cancelled (ID: {oid})")
            else:
                print(f"{label} order cancel error (ID: {oid}): {e}")


def update_sl_order_for_trade(symbol, signal_type, trade_id, amount, new_sl_price,
                               old_sl_order_id=None, tp2_price=None, old_tp_order_id=None,
                               exchange=None):
    """
    Move SL to breakeven after TP1 for a specific trade.
    1. Eski SL'yi order ID ile iptal et
    2. Yeni SL koy (reduceOnly + amount)
    3. (TP2 emirde kalir - degistirmiyoruz, zaten reduceOnly+amount ile bagimsiz)
    Returns: (new_sl_order_id, tp_order_id) - tp degismediyse old_tp_order_id doner
    """
    if not _is_auto_trade_enabled():
        return None, old_tp_order_id

    if not config.IS_FUTURES:
        return None, old_tp_order_id

    symbol = _to_futures_symbol(symbol)
    own_exchange = exchange is None
    if own_exchange:
        exchange = get_exchange()
        _sync_time_before_trade(exchange)

    if old_sl_order_id:
        try:
            exchange.cancel_order(old_sl_order_id, symbol)
            print(f"Old SL cancelled (ID: {old_sl_order_id})")
        except Exception as e:
            if _is_unknown_order_error(e):
                print(f"Old SL already gone (ID: {old_sl_order_id})")
            else:
                print(f"Old SL cancel error (ID: {old_sl_order_id}): {e}")

    close_side = 'sell' if "LONG" in signal_type else 'buy'
    new_sl_price = float(exchange.price_to_precision(symbol, new_sl_price))

    try:
        be_buffer = runtime_config.get_config().be_buffer_pct / 100.0
        if be_buffer > 0:
            if "LONG" in signal_type:
                new_sl_price = float(exchange.price_to_precision(symbol, new_sl_price * (1 + be_buffer)))
            else:
                new_sl_price = float(exchange.price_to_precision(symbol, new_sl_price * (1 - be_buffer)))
            print(f"BE buffer applied (%{be_buffer*100:.2f}): Yeni BE SL = {new_sl_price}")
    except Exception as e:
        print(f"BE buffer error: {e}")

    base_params = {
        'reduceOnly': True,
        'workingType': 'MARK_PRICE',
        'priceProtect': 'TRUE'
    }

    new_sl_order_id = None
    for attempt in range(MAX_4130_RETRIES + 1):
        try:
            sl_order = exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=close_side,
                amount=amount,
                price=None,
                params={**base_params, 'stopPrice': new_sl_price}
            )
            new_sl_order_id = sl_order.get('id')
            print(f"New SL (breakeven, reduceOnly): {new_sl_price} | Order ID: {new_sl_order_id}")
            break
        except Exception as e:
            err_str = str(e)
            if '-4130' in err_str and attempt < MAX_4130_RETRIES:
                print(f"Binance propagation delay (-4130), {RETRY_4130_DELAY_SEC}s waiting... ({attempt+1}/{MAX_4130_RETRIES+1})")
                time.sleep(RETRY_4130_DELAY_SEC)
                continue
            else:
                print(f"SL update error: {e}")
                break

    return new_sl_order_id, old_tp_order_id


def close_single_trade(symbol, signal_type, amount, exchange=None):
    """
    Close partial size (reduceOnly market).
    """
    if not _is_auto_trade_enabled():
        return

    own_exchange = exchange is None
    if own_exchange:
        exchange = get_exchange()
        _sync_time_before_trade(exchange)

    symbol = _to_futures_symbol(symbol)

    try:
        exchange.load_markets()
        side = 'sell' if "LONG" in signal_type else 'buy'
        params = {'reduceOnly': True} if config.IS_FUTURES else {}
        order = exchange.create_market_order(symbol, side, amount, params=params)
        print(f"Partial close: {side.upper()} {symbol} Qty: {amount}")
        return order
    except Exception as e:
        print(f"Partial close error: {e}")
        return None


def cancel_all_orders(symbol, exchange=None):
    """
    Cancel and verify all open orders for a symbol.
    WARNING: In multi-trade mode this removes other trades' orders too.
    Use only for full cleanup (e.g. migration, emergency).
    Prefer cancel_trade_orders() for normal closes.
    """
    own_exchange = exchange is None
    if own_exchange:
        exchange = get_exchange()
        _sync_time_before_trade(exchange)

    futures_symbol = _to_futures_symbol(symbol)
    clean_symbol = symbol.split(':')[0] if ':' in symbol else symbol
    base_symbol = clean_symbol.replace('/', '')
    symbol_variants = [symbol, base_symbol, futures_symbol, clean_symbol, f"{base_symbol}:USDT"]

    for attempt in range(MAX_API_RETRIES + 1):
        try:
            exchange.load_markets()

            batch_cancel_ok = False
            try:
                exchange.cancel_all_orders(futures_symbol)
                batch_cancel_ok = True
                print(f"Batch cancel called ({futures_symbol}): ok")
            except Exception as e:
                print(f"Batch cancel failed ({futures_symbol}): {e}")

            try:
                _cancel_algo_orders(symbol, exchange)
            except Exception as e:
                print(f"Algo cancel error: {e}")

            time.sleep(2)

            all_open_orders = []
            try:
                orders_all = exchange.fetch_open_orders()
                all_open_orders.extend(orders_all)
            except Exception:
                pass

            try:
                orders_symbol = exchange.fetch_open_orders(futures_symbol)
                existing_ids = {o.get('id') for o in all_open_orders}
                for o in orders_symbol:
                    if o.get('id') not in existing_ids:
                        all_open_orders.append(o)
            except Exception:
                pass

            target_orders = []
            for order in all_open_orders:
                order_symbol = order.get('symbol', '')
                order_info_symbol = order.get('info', {}).get('symbol', '')
                if (order_symbol in symbol_variants or
                    order_info_symbol in symbol_variants or
                    order_info_symbol == base_symbol):
                    target_orders.append(order)

            if not target_orders:
                if batch_cancel_ok:
                    print(f"{symbol}: Orders cleared (batch cancel)")
                else:
                    print(f"{symbol}: No open orders")
                return True

            cancelled = 0
            for order in target_orders:
                try:
                    exchange.cancel_order(order['id'], order.get('symbol', futures_symbol))
                    cancelled += 1
                except Exception as e:
                    print(f"Single cancel error ({order.get('id', '?')}): {e}")

            print(f"{symbol}: {cancelled}/{len(target_orders)} order cancelled")

            time.sleep(1.0)
            try:
                verify_orders = exchange.fetch_open_orders(futures_symbol)
                remaining_target = [
                    o for o in verify_orders
                    if o.get('symbol', '') in symbol_variants or
                       o.get('info', {}).get('symbol', '') in symbol_variants or
                       o.get('info', {}).get('symbol', '') == base_symbol
                ]
                if remaining_target:
                    print(f"WARNING: {symbol}: {len(remaining_target)} orders still not cleared!")
                    for order in remaining_target:
                        try:
                            exchange.cancel_order(order['id'], order.get('symbol', futures_symbol))
                        except Exception:
                            pass
                    return False
            except Exception:
                pass

            print(f"Verified: {symbol} all orders cleared")
            return True

        except Exception as e:
            if attempt < MAX_API_RETRIES and (_is_timestamp_error(e) or _is_transient_api_error(e)):
                print(f"API error (cancel), {RETRY_DELAY_SEC} s, retrying... ({e})")
                time.sleep(RETRY_DELAY_SEC)
                if own_exchange:
                    _sync_time_before_trade(exchange)
            else:
                print(f"Cancel failed after retries: {e}")
                return False


def _cancel_algo_orders(symbol, exchange):
    """Cancel Binance Futures conditional (algo) orders."""
    try:
        clean_symbol = symbol.split(':')[0] if ':' in symbol else symbol
        raw_symbol = clean_symbol.replace('/', '')
    except Exception:
        return

    try:
        response = exchange.fapiPrivateGetOpenAlgoOrders({'symbol': raw_symbol})
    except Exception as e:
        print(f"Algo order list failed ({raw_symbol}): {e}")
        return

    algos = []
    if isinstance(response, list):
        algos = response
    elif isinstance(response, dict):
        algos = response.get('data', response.get('orders', []))
        if not algos and 'algoId' in response:
            algos = [response]

    if not algos:
        return

    cancelled = 0
    for algo in algos:
        algo_id = algo.get('algoId') or algo.get('algo_id')
        if not algo_id:
            continue
        try:
            exchange.fapiPrivateDeleteAlgoOrder({'algoId': algo_id})
            cancelled += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"Algo cancel error (algoId={algo_id}): {e}")

    if cancelled:
        print(f"{cancelled} algo (conditional) orders cancelled")


def close_trade(symbol, signal_type):
    """
    Close position and cancel related TP/SL.
    WARNING: Closes the entire position; prefer close_single_trade() in multi-trade mode.
    """
    exchange = get_exchange()
    _sync_time_before_trade(exchange)
    symbol = _to_futures_symbol(symbol)

    for attempt in range(MAX_TIMESTAMP_RETRIES + 1):
        try:
            exchange.load_markets()

            try:
                cancel_all_orders(symbol, exchange=exchange)
            except Exception as e:
                print(f"Order cancel issue: {e}")

            positions = exchange.fetch_positions([symbol])
            position = None
            for p in positions:
                p_symbol = p.get('symbol', '')
                p_info_symbol = p.get('info', {}).get('symbol', '')
                if p_symbol == symbol or p_info_symbol == symbol.replace('/', ''):
                    position = p
                    break

            if position:
                amt = 0
                if 'contracts' in position and position['contracts']:
                    amt = abs(float(position['contracts']))
                elif 'info' in position and 'positionAmt' in position['info']:
                    amt = abs(float(position['info']['positionAmt']))

                if amt > 0:
                    side = 'sell' if "LONG" in signal_type else 'buy'
                    print(f"CLOSING POSITION: {side.upper()} {symbol} Qty: {amt}")
                    params = {'reduceOnly': True} if config.IS_FUTURES else {}
                    exchange.create_market_order(symbol, side, amt, params)
                    print("Position closed.")
                else:
                    print("Position already closed by Binance (SL/TP hit).")
            else:
                print("Position already closed by Binance.")
            return

        except Exception as e:
            if _is_timestamp_error(e) and attempt < MAX_TIMESTAMP_RETRIES:
                print(f"Time sync error (close), {RETRY_DELAY_SEC} s, retrying...")
                time.sleep(RETRY_DELAY_SEC)
                _sync_time_before_trade(exchange)
            else:
                print(f"Close position error: {e}")
                return
