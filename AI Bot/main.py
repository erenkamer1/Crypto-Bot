import time
import ccxt
import pandas as pd
from datetime import datetime, timezone
import config
import runtime_config
import indicators
import strategy
import telegram_bot
import telegram_commands
import trade_manager
import ml_data_logger
import order_executor
import signal_filter
import ml_prediction_logger
import shadow_trader
import order_tracker
import simulation_engine
import app_logger
from colorama import Fore, Style, init

init(autoreset=True)

import traceback

logger = app_logger.get_logger(__name__)

def _get_tp_sl_pcts():
    """TP/SL percentages from runtime config."""
    rc = runtime_config.get_config()
    sl_pct = rc.sl_pct / 100.0
    tp1_pct = rc.tp1_pct / 100.0
    tp2_pct = rc.tp2_pct / 100.0
    return sl_pct, tp1_pct, tp2_pct

def initialize_exchange():
    """Build exchange for public OHLCV data."""
    options = {'defaultType': 'spot'}
    if config.IS_FUTURES:
        options = {'defaultType': 'future'}

    exchange_config = {
        'enableRateLimit': True,
        'options': {
            **options,
            'adjustForTimeDifference': True,
        }
    }

    exchange = ccxt.binance(exchange_config)

    return exchange

def fetch_data(exchange, symbol, timeframe, limit):
    """Fetch OHLCV from Binance."""
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def _is_transient_api_error(e):
    """Transient API errors (retryable)."""
    err_str = str(e).lower()
    return (
        'exchangeinfo' in err_str or 'exchange info' in err_str or
        'timeout' in err_str or 'connection' in err_str or
        'network' in err_str or 'econnreset' in err_str or
        '502' in err_str or '503' in err_str or '429' in err_str or 'ratelimit' in err_str
    )


def _load_markets_with_retry(exchange, max_attempts=3, delay_sec=5):
    """Retry load_markets on transient failures."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            exchange.load_markets()
            return
        except Exception as e:
            last_err = e
            if _is_transient_api_error(e) and attempt < max_attempts - 1:
                logger.warning("Connection retry (%s/%s) in %ss...", attempt + 1, max_attempts, delay_sec)
                print(f"{Fore.YELLOW}Connection retry ({attempt + 1}/{max_attempts}) in {delay_sec}s...")
                time.sleep(delay_sec)
                continue
            raise
    raise last_err


def _handle_simulation_signal(symbol, signal, signal_direction, df, btc_df):
    """Simulation path: no live Binance orders."""
    sim = simulation_engine.get_engine()
    price = df.iloc[-1]['close']

    ml_confidence = None
    features = {}
    try:
        signal_type_str = signal_direction
        ml_confidence = signal_filter.get_confidence(
            signal_type=signal_type_str, df=df, entry_price=price, btc_df=btc_df
        )
        filter_instance = signal_filter.get_filter()
        features = filter_instance.prepare_features(df, price, btc_df, signal_type_str)
    except Exception:
        pass

    rc = runtime_config.get_config()
    sl_pct, tp1_pct, tp2_pct = _get_tp_sl_pcts()

    if "LONG" in signal:
        sl = price * (1 - sl_pct)
        tp1 = price * (1 + tp1_pct)
        tp2 = price * (1 + tp2_pct)
    else:
        sl = price * (1 + sl_pct)
        tp1 = price * (1 - tp1_pct)
        tp2 = price * (1 - tp2_pct)

    trade_setup = {
        "sl": round(sl, 6), "tp1": round(tp1, 6), "tp2": round(tp2, 6),
        "sl_pct": sl_pct * 100, "tp1_pct": tp1_pct * 100, "tp2_pct": tp2_pct * 100
    }

    if rc.use_custom_ml_threshold:
        eff_threshold = rc.ml_threshold
    else:
        eff_threshold = config.ML_CONFIDENCE_THRESHOLD

    can_sim, sim_block = sim.can_add_trade(symbol, signal_direction)

    if not can_sim:
        sim.log_ml_prediction(
            symbol=symbol, signal_type=signal_direction,
            confidence=ml_confidence or 0, threshold=eff_threshold,
            accepted=False, entry_price=price,
            reason=f"SIM: {sim_block}",
            features=features, trade_setup=trade_setup,
            timeframe=config.TIMEFRAME
        )
        shadow_trader.add_shadow_trade(
            symbol=symbol, signal_type=signal_direction,
            entry_price=price, trade_setup=trade_setup,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        logger.info("[SIM] Signal skipped (%s): %s - %s", symbol, signal_direction, sim_block)
        print(f"{Fore.YELLOW}[SIM] Signal skipped ({symbol}): {sim_block}")
        return

    sim.log_ml_prediction(
        symbol=symbol, signal_type=signal_direction,
        confidence=ml_confidence or 0, threshold=eff_threshold,
        accepted=True, entry_price=price,
        features=features, trade_setup=trade_setup,
        timeframe=config.TIMEFRAME
    )

    trade_obj = sim.open_trade(
        symbol=symbol, signal_type=signal, market_price=price,
        sl=sl, tp1=tp1, tp2=tp2, ml_confidence=ml_confidence
    )

    if trade_obj:
        sim.log_ml_training_data(
            signal_id=trade_obj["trade_id"],
            symbol=symbol, signal_type=signal, df=df,
            entry_price=trade_obj["entry"],
            sl=trade_obj["sl"], tp1=trade_obj["tp1"], tp2=trade_obj["tp2"],
            timeframe=config.TIMEFRAME, btc_df=btc_df
        )
        logger.info("[SIM] Trade opened: %s %s @ %.6f", symbol, signal, trade_obj["entry"])
        print(f"{Fore.GREEN}[SIM] Trade opened: {symbol} {signal} @ {trade_obj['entry']:.6f}")

        telegram_bot.send_signal(
            signal, df.iloc[-1], symbol,
            trade_obj["sl"], trade_obj["tp1"], trade_obj["tp2"],
            order_result=None
        )


def run_bot():
    app_logger.setup_logging()
    print(f"{Fore.CYAN}AI Bot 4 starting... scanning {len(config.WATCHLIST)} symbols. Timeframe: {config.TIMEFRAME}")
    logger.info(f"AI Bot 4 starting... scanning {len(config.WATCHLIST)} symbols. Timeframe: {config.TIMEFRAME}")

    try:
        exchange = initialize_exchange()
        logger.info("Connecting to exchange... (Futures: %s, Testnet: %s)", config.IS_FUTURES, config.USE_TESTNET)
        print(f"Connecting to exchange... (Futures: {config.IS_FUTURES}, Testnet: {config.USE_TESTNET})")
        _load_markets_with_retry(exchange)
        logger.info("Connected. %s markets loaded.", len(exchange.markets))
        print(f"Connected. {len(exchange.markets)} markets loaded.")
    except Exception as e:
        logger.exception("Exchange connection error")
        print(f"{Fore.RED}Exchange connection error: {e}")
        return

    btc_df = None

    tracker = order_tracker.OrderTracker(interval=5)
    tracker.start()

    while True:
        logger.info("--- Scan start (%s) ---", datetime.now().strftime('%H:%M:%S'))
        print(f"\n{Fore.YELLOW}--- Scan start ({datetime.now().strftime('%H:%M:%S')}) ---")

        for symbol in config.WATCHLIST:
            try:
                df = fetch_data(exchange, symbol, config.TIMEFRAME, config.LIMIT)
                df = indicators.calculate_all_indicators(df)
                last_row = df.iloc[-1]

                signal = strategy.check_signals(df, btc_df=btc_df, symbol=symbol)

                if signal:
                    signal_direction = "LONG" if "LONG" in signal else "SHORT"
                    rc = runtime_config.get_config()

                    if rc.simulation_mode:
                        _handle_simulation_signal(
                            symbol, signal, signal_direction, df, btc_df
                        )
                        signal = None

                    can_trade, block_reason = True, ""
                    if signal:
                        can_trade, block_reason = trade_manager.can_add_trade(symbol, signal_direction)

                    if signal and not can_trade:
                        logger.warning("Cannot open new trade for %s: %s", symbol, block_reason)
                        print(f"{Fore.YELLOW}Cannot open new trade for {symbol}: {block_reason}")

                        try:
                            entry_price = df.iloc[-1]['close']
                            signal_type = signal_direction

                            confidence = signal_filter.get_confidence(
                                signal_type=signal_type,
                                df=df,
                                entry_price=entry_price,
                                btc_df=btc_df
                            )

                            sl_pct, tp1_pct, tp2_pct = _get_tp_sl_pcts()
                            if "LONG" in signal:
                                sl = entry_price * (1 - sl_pct)
                                tp1 = entry_price * (1 + tp1_pct)
                                tp2 = entry_price * (1 + tp2_pct)
                            else:
                                sl = entry_price * (1 + sl_pct)
                                tp1 = entry_price * (1 - tp1_pct)
                                tp2 = entry_price * (1 - tp2_pct)

                            trade_setup = {
                                "sl": round(sl, 6),
                                "tp1": round(tp1, 6),
                                "tp2": round(tp2, 6),
                                "sl_pct": sl_pct * 100,
                                "tp1_pct": tp1_pct * 100,
                                "tp2_pct": tp2_pct * 100
                            }

                            filter_instance = signal_filter.get_filter()
                            features = filter_instance.prepare_features(df, entry_price, btc_df, signal_type)

                            rc_conf = runtime_config.get_config()
                            if rc_conf.use_custom_ml_threshold:
                                eff_threshold = rc_conf.ml_threshold
                            else:
                                eff_threshold = config.ML_CONFIDENCE_THRESHOLD

                            record = ml_prediction_logger.log_prediction(
                                symbol=symbol,
                                signal_type=signal_type,
                                confidence=confidence,
                                threshold=eff_threshold,
                                accepted=False,
                                entry_price=entry_price,
                                reason=f"{block_reason} (conf: {confidence:.2f})",
                                features=features,
                                trade_setup=trade_setup,
                                timeframe=config.TIMEFRAME
                            )

                            shadow_trader.add_shadow_trade(
                                symbol=symbol,
                                signal_type=signal_type,
                                entry_price=entry_price,
                                trade_setup=trade_setup,
                                timestamp=record.get('timestamp')
                            )

                            logger.info("Skipped trade added to shadow (conf: %.2f) - %s", confidence, symbol)
                            print(f"{Fore.CYAN}Skipped trade added to shadow (conf: {confidence:.2f})")

                        except Exception as e:
                            logger.exception("Skipped trade logging error")
                            print(f"{Fore.RED}Skipped trade logging error: {e}")

                        signal = None

                if signal:
                    logger.info("SIGNAL: %s -> %s | Price: %s | WT1: %.2f",
                                symbol, signal, last_row['close'], last_row['WT_1'])
                    print(f"{Fore.GREEN}SIGNAL: {symbol} -> {signal}")
                    print(f"   Price: {last_row['close']} | WT1: {last_row['WT_1']:.2f}")

                    price = last_row['close']
                    sl_pct, tp1_pct, tp2_pct = _get_tp_sl_pcts()
                    if "LONG" in signal:
                        sl = price * (1 - sl_pct)
                        tp1 = price * (1 + tp1_pct)
                        tp2 = price * (1 + tp2_pct)
                    else:
                        sl = price * (1 + sl_pct)
                        tp1 = price * (1 - tp1_pct)
                        tp2 = price * (1 - tp2_pct)

                    ml_confidence = None
                    try:
                        signal_type_str = "LONG" if "LONG" in signal else "SHORT"
                        ml_confidence = signal_filter.get_confidence(
                            signal_type=signal_type_str,
                            df=df,
                            entry_price=price,
                            btc_df=btc_df
                        )
                    except Exception:
                        pass

                    signal_id = trade_manager.add_trade(
                        symbol, signal, price, sl, tp1, tp2, ml_confidence=ml_confidence
                    )

                    ml_data_logger.log_signal(
                        signal_id=signal_id,
                        symbol=symbol,
                        signal_type=signal,
                        df=df,
                        entry_price=price,
                        sl=sl,
                        tp1=tp1,
                        tp2=tp2,
                        timeframe=config.TIMEFRAME,
                        btc_df=btc_df
                    )

                    order_result = order_executor.execute_trade(symbol, signal, price, sl=sl, tp1=tp1, tp2=tp2)

                    if order_result:
                        binance_oid = order_result.get('id')
                        if binance_oid:
                            trade_manager.update_binance_order_id(symbol, signal_id, binance_oid)

                        real_entry = order_result.get('real_entry')
                        r_sl = order_result.get('sl')
                        r_tp1 = order_result.get('tp1')
                        r_tp2 = order_result.get('tp2')
                        if real_entry and real_entry != price:
                            trade_manager.update_trade_entry_to_fill(
                                symbol, signal_id, real_entry, r_sl, r_tp1, r_tp2
                            )

                        amount = order_result.get('amount', 0)
                        sl_order_id = order_result.get('sl_order_id')
                        tp_order_id = order_result.get('tp_order_id')

                        trades = trade_manager.load_trades()
                        trade_list = trades.get(order_executor._to_futures_symbol(symbol),
                                                trades.get(symbol, []))
                        for t in trade_list:
                            if t.get("trade_id") == signal_id or t.get("signal_id") == signal_id:
                                t["amount"] = amount
                                if sl_order_id:
                                    t["sl_order_id"] = str(sl_order_id)
                                if tp_order_id:
                                    t["tp_order_id"] = str(tp_order_id)
                                break
                        trade_manager.save_trades(trades)

                    telegram_bot.send_signal(signal, last_row, symbol, sl, tp1, tp2, order_result=order_result)

                elif symbol == 'BTC/USDT':
                    btc_df = df.copy()
                    logger.info("BTC: Price: %s | WT1: %.2f", last_row['close'], last_row['WT_1'])
                    print(f"BTC: Price: {last_row['close']} | WT1: {last_row['WT_1']:.2f}")

                time.sleep(1)

            except Exception as e:
                logger.exception(f"Error ({symbol}): {e}")
                print(f"{Fore.RED}Error ({symbol}): {e}")

        logger.info("--- Scan done. Waiting for next round... ---")
        print(f"{Fore.CYAN}--- Scan done. Waiting for next round... ---")

        telegram_commands.check_for_commands()

        time.sleep(60 * 5)

if __name__ == "__main__":
    run_bot()
