# crypo-trade

Portfolio project: a **Binance USDT-M Futures** trading bot in Python with an ML (**XGBoost**) signal filter.

## Contents

Application code lives under [`AI Bot/`](AI Bot/). For setup, API security, and features, read **[AI Bot/README.md](AI Bot/README.md)**. ML file layout and config: **[AI Bot/ML_README.md](AI Bot/ML_README.md)**.

## Tech stack

| Area | Technologies |
|------|----------------|
| **Language** | Python 3 |
| **Exchange** | [ccxt](https://github.com/ccxt/ccxt) — Binance USDT-M Futures |
| **Data / indicators** | pandas, [ta](https://github.com/bukosabino/ta), NumPy |
| **Machine learning** | [XGBoost](https://xgboost.readthedocs.io/), scikit-learn (StandardScaler, RandomizedSearchCV, metrics), joblib |
| **Desktop UI** | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), CTkDateEntry |
| **Automation / reports** | openpyxl (Excel), optional Telegram (`requests` / bot flow in code) |
| **Config** | python-dotenv (`.env`), JSON runtime settings |
| **Packaging** | PyInstaller (see `build_exe.py`, `AIBot4.spec`) |

## ML pipeline (learning stages)

End-to-end flow from data to live filtering and improvement:

1. **Signal & feature logging** — Each candidate signal can write rich rows to `ml_training_data.jsonl` (`ml_data_logger.py`): indicators, BTC/market context, trade setup (SL/TP distances), later **labels** when trades close.
2. **Prediction logging** — Every ML accept/reject is stored in `ml_predictions.jsonl` (`ml_prediction_logger.py`) for offline analysis and retraining.
3. **Shadow outcomes** — Rejected signals can be tracked virtually (`shadow_trader.py`) so “would have won/lost” feeds **sample weights** and labels (`feature_engineering.py`: `shadow_wrong`, `shadow_correct`, etc.).
4. **Data merge & dedup** — `feature_engineering.load_training_data()` merges bot training files + prediction JSONLs, optional **meta-stacking** (AI1/2/3 confidence columns), and deduplicates records.
5. **Feature preparation** — Flatten nested JSON → numeric matrix; chronological sort; impute missing values; binary or multi-class labels.
6. **Train / test split** — **Chronological** split (default last 20% test) to reduce look-ahead bias; optional stratified random split.
7. **Class balance & sample weights** — `scale_pos_weight` for XGBoost; per-row weights from source type (real vs shadow).
8. **Hyperparameter search** — RandomizedSearchCV on key XGBoost params (AUC on CV).
9. **Model training** — XGBoost classifier with early stopping on a hold-out set; exports `signal_classifier.pkl`, `feature_scaler.pkl`, `model_meta.json`.
10. **Threshold tuning** — Grid search on validation probabilities for F1 / trading-style metrics; optimal threshold stored in metadata.
11. **Inference** — `signal_filter.py` loads model + scaler, builds the same feature vector as training, outputs confidence vs `ML_CONFIDENCE_THRESHOLD`.
12. **Improvement loop** — `improve_model.py` (`--analyze`, `--retrain`, `--full`) to inspect prediction logs and re-run `ml_training/train_model.py` as new labeled data accumulates.

## Quick start

```bash
cd "AI Bot"
pip install -r requirements.txt
cp .env.example .env
cp runtime_settings.example.json runtime_settings.json
```

Fill in `.env` and `runtime_settings.json` with your own keys locally; these files are not tracked by git.

## Security

Revoke and rotate any API keys that were ever exposed; the public repo only ships example templates.
