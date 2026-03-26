import config
import runtime_config
from colorama import Fore, Style

try:
    import signal_filter
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print(f"{Fore.YELLOW}ML filter module not found; ML disabled.{Style.RESET_ALL}")


def check_divergence(df, lookback=5):
    """
    Simple WaveTrend divergence detection.
    lookback: bars to search for swing highs/lows
    """
    if len(df) < lookback + 5:
        return None

    current = df.iloc[-1]
    prev = df.iloc[-2]

    # Bearish divergence (SHORT)
    threshold_check = prev['WT_1'] > config.WT_BOUGHT_LEVEL_1 or df['WT_1'].iloc[-5:-1].max() > config.WT_BOUGHT_LEVEL_1

    if threshold_check:
        curr_wt_high = df['WT_1'].iloc[-5:-1].max()
        curr_price_high = df['high'].iloc[-5:-1].max()

        prev_wt_high = df['WT_1'].iloc[-30:-5].max()
        prev_price_high = df['high'].iloc[-30:-5].max()

        if curr_price_high > prev_price_high:
            if curr_wt_high < prev_wt_high:
                return "SHORT (Bearish Divergence)"

    # Bullish divergence (LONG)
    threshold_check_bull = prev['WT_1'] < config.WT_SOLD_LEVEL_1 or df['WT_1'].iloc[-5:-1].min() < config.WT_SOLD_LEVEL_1

    if threshold_check_bull:
        curr_wt_low = df['WT_1'].iloc[-5:-1].min()
        curr_price_low = df['low'].iloc[-5:-1].min()

        prev_wt_low = df['WT_1'].iloc[-30:-5].min()
        prev_price_low = df['low'].iloc[-30:-5].min()

        if curr_price_low < prev_price_low:
            if curr_wt_low > prev_wt_low:
                return "LONG (Bullish Divergence)"

    return None


def check_signals(df, btc_df=None, symbol=None):
    """
    Main signal check with optional ML filter.

    Args:
        df: OHLCV + indicators
        btc_df: BTC context for ML (optional)
        symbol: market symbol for logging

    Returns:
        Signal string or None
    """
    signal = check_divergence(df)

    if signal:
        if config.USE_ADX_FILTER:
            current_adx = df.iloc[-1]['ADX']
            if current_adx > 25:
                pass

        if config.USE_ML_FILTER and ML_AVAILABLE:
            try:
                entry_price = df.iloc[-1]['close']
                signal_type = "LONG" if "LONG" in signal else "SHORT"

                confidence = signal_filter.get_confidence(
                    signal_type=signal_type,
                    df=df,
                    entry_price=entry_price,
                    btc_df=btc_df
                )

                rc = runtime_config.get_config()
                if rc.use_custom_ml_threshold:
                    min_threshold = rc.ml_threshold
                else:
                    min_threshold = config.ML_CONFIDENCE_THRESHOLD

                if config.ML_LOG_ALL_PREDICTIONS:
                    print(f"{Fore.CYAN}ML confidence: {confidence:.2f} (threshold: {min_threshold}){Style.RESET_ALL}")

                accepted = confidence >= min_threshold
                reason = None if accepted else f"conf {confidence:.2f} < {min_threshold}"

                try:
                    import ml_prediction_logger

                    filter_instance = signal_filter.get_filter()
                    features = filter_instance.prepare_features(df, entry_price, btc_df, signal_type)

                    if "LONG" in signal:
                        sl = entry_price * (1 - config.STOP_LOSS_PCT)
                        tp1 = entry_price * (1 + config.TAKE_PROFIT_1_PCT)
                        tp2 = entry_price * (1 + config.TAKE_PROFIT_2_PCT)
                    else:
                        sl = entry_price * (1 + config.STOP_LOSS_PCT)
                        tp1 = entry_price * (1 - config.TAKE_PROFIT_1_PCT)
                        tp2 = entry_price * (1 - config.TAKE_PROFIT_2_PCT)

                    trade_setup = {
                        "sl": round(sl, 6),
                        "tp1": round(tp1, 6),
                        "tp2": round(tp2, 6),
                        "sl_pct": config.STOP_LOSS_PCT * 100,
                        "tp1_pct": config.TAKE_PROFIT_1_PCT * 100,
                        "tp2_pct": config.TAKE_PROFIT_2_PCT * 100
                    }

                    ml_prediction_logger.log_prediction(
                        symbol=symbol or "UNKNOWN",
                        signal_type=signal_type,
                        confidence=confidence,
                        threshold=min_threshold,
                        accepted=accepted,
                        entry_price=entry_price,
                        reason=reason,
                        features=features,
                        trade_setup=trade_setup,
                        timeframe=config.TIMEFRAME
                    )
                except ImportError:
                    pass

                if not accepted and config.ML_SKIP_LOW_CONFIDENCE:
                    print(f"{Fore.YELLOW}ML filter: signal rejected (conf {confidence:.2f} < {min_threshold}){Style.RESET_ALL}")

                    try:
                        import shadow_trader
                        import ml_prediction_logger
                        logger = ml_prediction_logger.get_logger()
                        if logger.predictions:
                            last_pred = logger.predictions[-1]
                            shadow_trader.add_shadow_trade(
                                symbol=symbol,
                                signal_type=signal_type,
                                entry_price=entry_price,
                                trade_setup=trade_setup,
                                timestamp=last_pred.get('timestamp')
                            )
                    except Exception as e:
                        print(f"{Fore.RED}Shadow trade error: {e}{Style.RESET_ALL}")

                    return None

                print(f"{Fore.GREEN}ML OK: {signal} (conf: {confidence:.2f}){Style.RESET_ALL}")

            except Exception as e:
                print(f"{Fore.RED}ML filter error: {e}{Style.RESET_ALL}")

        return signal

    return None
