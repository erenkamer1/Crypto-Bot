# crypo-trade

Portfolio project: a **Binance USDT-M Futures** trading bot in Python with an ML (XGBoost) signal filter.

## Contents

Application code lives under [`AI Bot/`](AI Bot/). For setup, API security, and a short architecture overview, read:

- **[AI Bot/README.md](AI Bot/README.md)**

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
