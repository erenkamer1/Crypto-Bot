#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance Excel export vs signal history.
Matches Excel rows to signal records and checks TP/SL alignment.
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXCEL_PATH = SCRIPT_DIR / "binance trade files" / "Export Trade History (1).xlsx"
SIGNAL_FILE = SCRIPT_DIR / "signal_history.json"

TARGET_TP_PCT = 3
TARGET_SL_PCT = 4
TRADE_AMOUNT_USDT = 13


def load_signals():
    with open(SIGNAL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    signals = data.get("signals", data) if isinstance(data, dict) else data
    return [s for s in signals if isinstance(s, dict)]


def symbol_to_signal_format(sym):
    """PIPPINUSDT -> PIPPIN/USDT"""
    if not sym or sym == "USDT":
        return ""
    return sym.replace("USDT", "") + "/USDT"


def parse_excel_date(s):
    if pd.isna(s):
        return None
    try:
        if isinstance(s, str):
            return datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        return s
    except Exception:
        return None


def load_excel_trades():
    df = pd.read_excel(EXCEL_PATH)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def main():
    if not EXCEL_PATH.exists():
        print(f"ERROR: Excel file not found: {EXCEL_PATH}")
        return

    df = load_excel_trades()
    signals = load_signals()

    date_col = None
    for c in df.columns:
        if "date" in c.lower() and "utc" in c.lower():
            date_col = c
            break
        if "date" in c.lower():
            date_col = date_col or c
    if not date_col:
        date_col = df.columns[0]

    symbol_col = next((c for c in df.columns if "symbol" in c.lower() or c == "Symbol"), "Symbol")
    side_col = next((c for c in df.columns if "side" in c.lower()), "Side")
    amount_col = next((c for c in df.columns if "amount" in c.lower() and "asset" not in c.lower()), "Amount")
    profit_col = next((c for c in df.columns if "realized" in c.lower() and "profit" in c.lower()), "Realized Profit")
    price_col = next((c for c in df.columns if "price" in c.lower()), "Price")

    df_valid = df[df[profit_col].notna()].copy()
    df_closed = df_valid[df_valid[profit_col].astype(float) != 0]

    if df_closed.empty:
        df_closed = df_valid

    print("=" * 100)
    print("BINANCE EXCEL vs SIGNAL HISTORY")
    print("=" * 100)
    print(f"File: {EXCEL_PATH.name}")
    print(f"Total rows (Excel): {len(df)}")
    print(f"Rows with P&L: {len(df_closed)}")
    print(f"Targets: TP {TARGET_TP_PCT}% | SL {TARGET_SL_PCT}%")
    print("=" * 100)

    results = []
    for idx, row in df_closed.iterrows():
        date_str = str(row[date_col])[:19].replace("T", " ")
        symbol_raw = str(row[symbol_col]).strip()
        symbol_slash = symbol_to_signal_format(symbol_raw)
        side = str(row.get(side_col, "")).strip().upper()
        amount = float(row.get(amount_col, 0) or 0)
        realized = float(row.get(profit_col, 0) or 0)
        price = float(row.get(price_col, 0) or 0)

        if amount <= 0:
            amount = TRADE_AMOUNT_USDT

        pct_from_excel = (realized / amount * 100) if amount else 0

        best_match = None
        best_diff = float("inf")
        dt = parse_excel_date(row[date_col])

        for sig in signals:
            if sig.get("symbol") != symbol_slash:
                continue
            if sig.get("status") != "CLOSED":
                continue
            close_time = sig.get("close_time") or ""
            try:
                sig_dt = datetime.strptime(close_time[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if dt:
                diff = abs((dt - sig_dt).total_seconds())
                if diff < best_diff and diff < 3600 * 2:
                    best_diff = diff
                    best_match = sig

        match_tag = "other"
        if abs(pct_from_excel - TARGET_TP_PCT) < 1.0:
            uyum = f"TP {TARGET_TP_PCT}% match ({pct_from_excel:.2f}%)"
            match_tag = "tp"
        elif abs(pct_from_excel - (-TARGET_SL_PCT)) < 1.0:
            uyum = f"SL {TARGET_SL_PCT}% match ({pct_from_excel:.2f}%)"
            match_tag = "sl"
        elif abs(pct_from_excel) < 0.5:
            uyum = "Breakeven/Manual"
        elif pct_from_excel > 0:
            uyum = f"Outside TP target ({pct_from_excel:.2f}%)"
        else:
            uyum = f"Outside SL target ({pct_from_excel:.2f}%)"

        sig_info = ""
        if best_match:
            sig_info = f"Signal: {best_match.get('close_reason','')} entry={best_match.get('entry')}"
        else:
            sig_info = "No signal match"

        results.append({
            "date": date_str,
            "symbol": symbol_raw.replace("USDT", ""),
            "side": side,
            "amount": amount,
            "realized": realized,
            "pct": pct_from_excel,
            "uyum": uyum,
            "match_tag": match_tag,
            "sig": sig_info,
        })

    print(f"\n{'Date':<22} {'Symbol':<10} {'Side':<5} {'Amount':<10} {'Realized':<12} {'P&L %':<12} {'TP/SL':<28} {'Signal'}")
    print("-" * 120)
    for r in results:
        print(f"{r['date']:<22} {r['symbol']:<10} {r['side']:<5} {r['amount']:<10.2f} {r['realized']:<+12.4f} {r['pct']:>+10.2f}%   {r['uyum']:<28} {r['sig'][:40]}")

    total_realized = sum(r["realized"] for r in results)
    tp_ok = sum(1 for r in results if r.get("match_tag") == "tp")
    sl_ok = sum(1 for r in results if r.get("match_tag") == "sl")
    diger = len(results) - tp_ok - sl_ok

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"  TP {TARGET_TP_PCT}% target aligned: {tp_ok}")
    print(f"  SL {TARGET_SL_PCT}% target aligned: {sl_ok}")
    print(f"  Other (breakeven/manual/off-target): {diger}")
    print(f"  Total realized P&L (Excel): {total_realized:+.4f} USDT")
    print()


if __name__ == "__main__":
    main()
