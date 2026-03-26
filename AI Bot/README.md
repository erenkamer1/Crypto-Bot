# Crypto Futures Bot — Python, ML, Binance (USDT-M)

Portfolio / demo project: multi-coin scanning with technical indicators and an XGBoost-based signal filter on Binance Futures; optional Telegram notifications and Excel reports. Supports live trading or **simulation** mode.

## Features (summary)

- **Strategy:** Multi-coin scan, indicators (`indicators.py`), signal generation (`strategy.py`, `signal_filter.py`).
- **ML:** Training under `ml_training/`, artifacts under `models/` (`signal_classifier.pkl`, `feature_scaler.pkl`, `model_meta.json`).
- **Exchange:** Binance USDT-M Futures via `ccxt`; TP/SL and order flow (`order_executor.py`, `order_tracker.py`).
- **UI:** `gui_app.py` (CustomTkinter) for runtime settings and logs.

## Setup

```bash
cd "AI Bot"
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

1. Environment variables: copy `.env.example` to `.env` and edit (never commit secrets).

   ```bash
   cp .env.example .env
   ```

2. Runtime settings (GUI / API keys): copy the example file.

   ```bash
   cp runtime_settings.example.json runtime_settings.json
   ```

   Then fill Binance API keys only in the **local** `runtime_settings.json` (via GUI or editor). This file is excluded via `.gitignore`.

3. Bot: `python main.py` or GUI: `python gui_app.py`.

## Security (read this)

- Never commit real API keys, secrets, or Telegram tokens.
- If keys were exposed anywhere, revoke them on Binance and Telegram; deleting from the repo alone is not enough.

## Project layout (short)

| Path | Description |
|------|----------------|
| `main.py` | Scan loop, signal and order flow |
| `config.py` | Environment variables, watchlist |
| `runtime_config.py` | Sync with `runtime_settings.json` and GUI |
| `ml_training/` | Model training (`train_model.py`) |
| `models/` | Trained model and metadata |

See `ML_README.md` for ML details.
