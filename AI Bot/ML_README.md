# AI Bot — ML system documentation

This document describes the ML (machine learning) signal filtering stack.

---

## File layout

```
AI Bot/
├── Core ML modules
│   ├── signal_filter.py          # Real-time signal filtering
│   ├── ml_prediction_logger.py   # Prediction logging
│   └── improve_model.py          # Model improvement utilities
│
├── ml_training/
│   ├── train_model.py            # Main training script
│   └── feature_engineering.py    # Data preparation
│
├── models/
│   ├── signal_classifier.pkl    # XGBoost model
│   ├── feature_scaler.pkl       # Normalization
│   └── model_meta.json          # Metadata
│
├── Data files (generated)
│   ├── ml_training_data.jsonl
│   ├── ml_predictions.jsonl
│   └── ml_predictions.log
│
└── config.py                    # ML-related settings
```

---

## Module notes

### 1. `signal_filter.py`
**Purpose:** Real-time signal filtering

```python
# Called from strategy.py
confidence = signal_filter.get_confidence(signal_type, df, entry_price, btc_df)
```

**Behavior:**
- Loads the trained model
- Builds features for the signal
- Returns a 0–1 confidence score
- Rejects signals below the threshold

---

### 2. `ml_prediction_logger.py`
**Purpose:** Persist all ML predictions

**Outputs:**
- `ml_predictions.log` — text log
- `ml_predictions.jsonl` — JSONL for analysis

**Example log:**
```
[2026-02-03T14:30:00] BTC/USDT | LONG | Conf: 0.72 | ACCEPT
[2026-02-03T14:35:00] ETH/USDT | SHORT | Conf: 0.43 | REJECT
```

---

### 3. `improve_model.py`
**Purpose:** Analyze performance and retrain

| Command | Description |
|---------|-------------|
| `python improve_model.py --guide` | Show guide |
| `python improve_model.py --analyze` | Performance analysis |
| `python improve_model.py --retrain` | Retrain model |
| `python improve_model.py --full` | Full pipeline |

---

### 4. `ml_training/train_model.py`
**Purpose:** Train the XGBoost classifier

```bash
cd ml_training
python train_model.py
```

**Outputs:**
- `models/signal_classifier.pkl`
- `models/feature_scaler.pkl`
- `models/model_meta.json`

---

### 5. `ml_training/feature_engineering.py`
**Purpose:** Turn JSONL into ML-ready tables

**Steps:**
- Flatten nested JSON
- Fill missing values
- Encode labels
- Train/test split

---

### 6. `ml_training_data.jsonl`
**Purpose:** Primary training dataset

**Contents:** signal records with indicators, BTC context, regime features, and outcome labels.

---

### 7. `models/`
- `signal_classifier.pkl` — XGBoost binary classifier
- `feature_scaler.pkl` — `StandardScaler`
- `model_meta.json` — feature names, metrics, version

---

## Config (`config.py`)

```python
USE_ML_FILTER = True
ML_CONFIDENCE_THRESHOLD = 0.55
ML_SKIP_LOW_CONFIDENCE = True
ML_LOG_ALL_PREDICTIONS = True
ML_SAVE_PREDICTIONS_JSONL = True
ML_PAPER_TRADING = True
```

---

## Flow

```
1. Bot starts → signal_filter loads model
        ↓
2. Signal detected → features computed
        ↓
3. Model scores confidence
        ↓
4. Threshold → accept / reject
        ↓
5. ml_prediction_logger records decision
        ↓
6. Trade opens or skips
        ↓
7. Trade closes → ml_data_logger updates outcome
        ↓
8. Periodically → improve_model.py analyze & retrain
```

---

## Shadow trading

**What:** Shadow tracks signals that could not be taken as live trades.

**Why:**
- Estimate what would have happened to rejected signals
- Evaluate model quality better
- Collect richer training data

**When active:**

| Case | Shadow |
|------|--------|
| ML confidence below threshold | Yes |
| Open position on same symbol | Yes |
| Signal taken as live trade | No |

### Breakeven trail (simplified)

Price hits TP1 → trade does not close; SL moves to breakeven; then TP2 or SL.

### Outcome types

| Outcome | Meaning |
|---------|---------|
| `tp1_then_tp2` | TP1 then TP2 |
| `tp1_then_sl` | TP1 then SL at breakeven |
| `would_full_win` | Direct TP2 |
| `would_lose` | Hit SL |

---

## Maintenance

1. Every ~200 new signals → `python improve_model.py --retrain`
2. If win rate drops → raise threshold (e.g. 0.60, 0.65)
3. If too few signals pass → lower threshold (e.g. 0.50, 0.45)
4. On model load errors → set `USE_ML_FILTER = False` temporarily

---

## Disclaimer

Backtest / training metrics are optimistic; live performance is typically lower. Use proper risk management.
