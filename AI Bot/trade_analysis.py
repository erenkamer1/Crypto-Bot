#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trade analysis: signal history, TP/SL alignment, P&L %.
Targets: TP 3%, SL 4% | 13 USDT per trade (configurable below).
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SIGNAL_FILE = SCRIPT_DIR / "signal_history.json"

TARGET_TP_PCT = 3
TARGET_SL_PCT = 4
TRADE_AMOUNT_USDT = 13
START_BALANCE = 135.90


def load_signals():
    with open(SIGNAL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    signals = data.get("signals", data) if isinstance(data, dict) else data
    return [s for s in signals if isinstance(s, dict)]


def parse_date(s):
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def analyze_trades(from_date: str = "2026-02-14"):
    """Analyze closed trades from from_date onward."""
    signals = load_signals()
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")

    closed = [
        s for s in signals
        if s.get("status") == "CLOSED"
        and parse_date(s.get("start_time", ""))
        and parse_date(s.get("start_time", "")) >= from_dt
    ]
    closed.sort(key=lambda x: x.get("start_time", ""))

    print("=" * 90)
    print("AI BOT V2 — TRADE ANALYSIS")
    print("=" * 90)
    print(f"Targets: TP {TARGET_TP_PCT}% | SL {TARGET_SL_PCT}% | {TRADE_AMOUNT_USDT} USDT per trade")
    print(f"Range: from {from_date} (closed trades only)")
    print("=" * 90)

    tp_ok = 0
    sl_ok = 0
    breakeven = 0
    tp_fail = 0
    sl_fail = 0

    rows = []
    for i, s in enumerate(closed):
        symbol = s.get("symbol", "").replace("/USDT", "")
        entry = s.get("entry", 0)
        sl = s.get("sl", 0)
        tp2 = s.get("tp2", 0)
        reason = s.get("close_reason", "")
        profit_pct = s.get("profit_pct")
        start = s.get("start_time", "")
        close_time = s.get("close_time", "")

        if reason == "TP2":
            if profit_pct == TARGET_TP_PCT:
                tp_ok += 1
                uyum = "OK TP 3% target"
            else:
                tp_fail += 1
                uyum = f"TP expected 3%, got {profit_pct}%"
        elif reason == "SL":
            if profit_pct == -TARGET_SL_PCT:
                sl_ok += 1
                uyum = "OK SL 4% target"
            else:
                sl_fail += 1
                uyum = f"SL expected -4%, got {profit_pct}%"
        else:
            breakeven += 1
            uyum = f"Breakeven/Manual (profit_pct={profit_pct})"

        if profit_pct is not None:
            pnl_usdt = TRADE_AMOUNT_USDT * (profit_pct / 100)
        else:
            pnl_usdt = 0

        rows.append({
            "no": i + 1,
            "symbol": symbol,
            "start": start,
            "close": close_time,
            "entry": entry,
            "reason": reason,
            "profit_pct": profit_pct,
            "pnl_usdt": pnl_usdt,
            "uyum": uyum,
        })

    print(f"\n{'No':<4} {'Symbol':<10} {'Open':<20} {'Close':<20} {'Why':<6} {'P&L %':<12} {'USDT (13 base)':<14} {'TP/SL'}")
    print("-" * 130)
    for r in rows:
        pct_str = f"%{r['profit_pct']:+.1f}" if r['profit_pct'] is not None else "---"
        usdt_str = f"{r['pnl_usdt']:+.2f}" if r['pnl_usdt'] != 0 else "0.00"
        print(f"{r['no']:<4} {r['symbol']:<10} {r['start'][:19]:<20} {r['close'][:19] if r['close'] else '---':<20} {r['reason']:<6} {pct_str:<12} {usdt_str:<14} {r['uyum']:<25}")

    total_pnl = sum(r["pnl_usdt"] for r in rows)
    print("\n" + "=" * 90)
    print("TP/SL TARGET SUMMARY")
    print("=" * 90)
    print(f"  TP closed at target ({TARGET_TP_PCT}%): {tp_ok}")
    print(f"  TP closed off target:              {tp_fail}")
    print(f"  SL closed at target ({TARGET_SL_PCT}%): {sl_ok}")
    print(f"  SL closed off target:              {sl_fail}")
    print(f"  Breakeven/Manual:                  {breakeven}")
    print()
    print("P&L SUMMARY")
    print("=" * 90)
    print(f"  Trades:           {len(rows)}")
    print(f"  Total PnL (base): {total_pnl:+.2f} USDT")
    print(f"  Start balance:    {START_BALANCE} USDT")
    print(f"  Est. end balance: {START_BALANCE + total_pnl:.2f} USDT")
    print()

    print("=" * 90)
    print("EXCEL (BINANCE) CROSS-CHECK")
    print("=" * 90)
    print("To match Binance exports to signals:")
    print("  1. Binance > Trade History > Export CSV")
    print("  2. Map Symbol column PIPPINUSDT -> PIPPIN format if needed")
    print("  3. Align Date(UTC) with start_time/close_time")
    print("  4. Realized Profit / 13 ≈ P&L % (if 13 USDT sizing)")
    print()


if __name__ == "__main__":
    analyze_trades("2026-02-14")
