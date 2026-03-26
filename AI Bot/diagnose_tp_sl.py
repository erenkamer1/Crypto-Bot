#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TP/SL diagnostic: compare signals vs Binance export (read-only).
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SIGNAL_FILE = SCRIPT_DIR / "signal_history.json"
EXCEL_PATH = SCRIPT_DIR / "binance trade files" / "Export Trade History (1).xlsx"

TARGET_TP_PCT = 3
TARGET_SL_PCT = 4


def load_signals():
    if not SIGNAL_FILE.exists():
        return []
    with open(SIGNAL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("signals", []) if isinstance(data, dict) else data


def run_diagnosis():
    signals = [s for s in load_signals() if isinstance(s, dict)]
    closed = [s for s in signals if s.get("status") == "CLOSED"]
    closed.sort(key=lambda x: x.get("close_time") or "")

    print("=" * 90)
    print("TP/SL DIAGNOSTIC (read-only)")
    print("=" * 90)
    print(f"Closed trades in history: {len(closed)}")
    print(f"Target: TP {TARGET_TP_PCT}% | SL {TARGET_SL_PCT}%")
    print("=" * 90)

    print("\nEntry / SL / TP consistency (last 20 closed):")
    print("-" * 90)
    for s in closed[-20:]:
        sym = s.get("symbol", "").replace("/USDT", "")
        entry = s.get("entry", 0)
        sl = s.get("sl", 0)
        tp2 = s.get("tp2", 0)
        reason = s.get("close_reason", "")
        pct = s.get("profit_pct")

        if "LONG" in str(s.get("signal", "")):
            sl_pct = (entry - sl) / entry * 100 if entry else 0
            tp_pct = (tp2 - entry) / entry * 100 if entry else 0
        else:
            sl_pct = (sl - entry) / entry * 100 if entry else 0
            tp_pct = (entry - tp2) / entry * 100 if entry else 0

        ok = "OK" if abs(sl_pct - TARGET_SL_PCT) < 0.1 and abs(tp_pct - TARGET_TP_PCT) < 0.1 else "!"
        print(f"  {sym:<10} entry={entry} sl={sl:.5f} tp2={tp2:.5f} | sl%={sl_pct:.2f} tp%={tp_pct:.2f} | {reason} {pct}% {ok}")

    if EXCEL_PATH.exists():
        try:
            import pandas as pd
            df = pd.read_excel(EXCEL_PATH)
            profit_col = next((c for c in df.columns if "realized" in str(c).lower() and "profit" in str(c).lower()), None)
            if profit_col:
                closed_rows = df[df[profit_col].notna() & (df[profit_col].astype(float) != 0)]
                print(f"\nExcel: {len(closed_rows)} PnL rows")
        except Exception as e:
            print(f"\nExcel read failed: {e}")

    print("\n" + "=" * 90)
    print("Done.")
    print("=" * 90)


if __name__ == "__main__":
    run_diagnosis()
