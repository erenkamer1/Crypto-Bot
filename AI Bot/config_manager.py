"""
Config manager: setting definitions, validation, formatting.
Used by telegram_commands and telegram_wizard.
"""

import runtime_config

# Setting defs: label, min, max, unit, type, property, display_fmt, wizard_options
SETTINGS_DEFS = {
    "ml_threshold": {
        "label": "ML Confidence",
        "min": 0.0,
        "max": 1.0,
        "unit": "",
        "type": float,
        "property": "ml_threshold",
        "display_fmt": "{:.2f}",
        "wizard_options": ["0.45", "0.50", "0.55", "0.60", "0.65"],
        "order": 1,
    },
    "tp1_pct": {
        "label": "TP1",
        "min": 0.1,
        "max": 50.0,
        "unit": "%",
        "type": float,
        "property": "tp1_pct",
        "display_fmt": "{:.1f}",
        "wizard_options": ["1.0", "1.2", "1.5", "2.0", "2.5"],
        "order": 2,
    },
    "tp2_pct": {
        "label": "TP2",
        "min": 0.1,
        "max": 50.0,
        "unit": "%",
        "type": float,
        "property": "tp2_pct",
        "display_fmt": "{:.1f}",
        "wizard_options": ["2.0", "2.5", "3.0", "4.0", "5.0"],
        "order": 3,
    },
    "sl_pct": {
        "label": "SL",
        "min": 0.1,
        "max": 50.0,
        "unit": "%",
        "type": float,
        "property": "sl_pct",
        "display_fmt": "{:.1f}",
        "wizard_options": ["0.5", "0.8", "1.0", "2.0", "4.0"],
        "order": 4,
    },
    "sl_buffer_pct": {
        "label": "Initial SL buffer",
        "min": 0.0,
        "max": 1.0,
        "unit": "%",
        "type": float,
        "property": "sl_buffer_pct",
        "display_fmt": "{:.2f}",
        "wizard_options": ["0.00", "0.03", "0.05", "0.08", "0.10"],
        "order": 5,
    },
    "be_buffer_pct": {
        "label": "BE SL Buffer",
        "min": 0.0,
        "max": 1.0,
        "unit": "%",
        "type": float,
        "property": "be_buffer_pct",
        "display_fmt": "{:.2f}",
        "wizard_options": ["0.00", "0.05", "0.08", "0.10", "0.15"],
        "order": 6,
    },
    "fixed_trade_amount_usdt": {
        "label": "USDT per trade",
        "min": 1.0,
        "max": 100000.0,
        "unit": " USDT",
        "type": float,
        "property": "fixed_trade_amount_usdt",
        "display_fmt": "{:.1f}",
        "wizard_options": ["10", "50", "100", "250", "500"],
        "order": 7,
    },
    "allow_new_trades": {
        "label": "New trades",
        "type": bool,
        "property": "allow_new_trades",
        "display_fmt": None,
        "wizard_options": None,
        "order": 8,
    },
    "show_balance_info": {
        "label": "Balance info",
        "type": bool,
        "property": "show_balance_info",
        "display_fmt": None,
        "wizard_options": None,
        "order": 9,
    },
}

ORDERED_KEYS = sorted(SETTINGS_DEFS.keys(), key=lambda k: SETTINGS_DEFS[k]["order"])


def get_setting(key: str):
    """Read setting from runtime config."""
    defn = SETTINGS_DEFS.get(key)
    if not defn:
        raise KeyError(f"Unknown setting: {key}")
    rc = runtime_config.get_config()
    return getattr(rc, defn["property"])


def set_setting(key: str, value):
    """Write setting to runtime config and save file."""
    defn = SETTINGS_DEFS.get(key)
    if not defn:
        raise KeyError(f"Unknown setting: {key}")
    rc = runtime_config.get_config()
    setattr(rc, defn["property"], value)
    rc.save_to_file()


def validate_value(key: str, raw_value: str):
    """
    Validate user input; returns parsed value or raises ValueError.
    """
    defn = SETTINGS_DEFS.get(key)
    if not defn:
        raise ValueError(f"Unknown setting: {key}")

    val_type = defn["type"]

    if val_type == bool:
        lower = raw_value.strip().lower()
        if lower in ("true", "1", "evet", "açık", "aktif", "on", "aç", "yes"):
            return True
        elif lower in ("false", "0", "hayır", "kapalı", "pasif", "off", "kapat", "no"):
            return False
        else:
            raise ValueError(
                "Invalid value. Accepted:\n"
                "On: yes, true, on, active, 1 (or Turkish: evet, açık, aktif)\n"
                "Off: no, false, off, 0 (or Turkish: hayır, kapalı, pasif)"
            )

    if val_type == float:
        try:
            parsed = float(raw_value.strip().replace(",", ".").replace("%", ""))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid number: '{raw_value}'. Enter a numeric value.")

        min_val = defn.get("min")
        max_val = defn.get("max")

        if parsed < 0:
            raise ValueError("Negative values are not allowed.")

        if min_val is not None and parsed < min_val:
            raise ValueError(f"Minimum: {min_val}")

        if max_val is not None and parsed > max_val:
            raise ValueError(f"Maximum: {max_val}")

        return parsed

    raise ValueError(f"Unsupported type: {val_type}")


def format_setting(key: str) -> str:
    """Format setting for display."""
    defn = SETTINGS_DEFS.get(key)
    if not defn:
        return "?"

    value = get_setting(key)
    val_type = defn["type"]

    if val_type == bool:
        return "On" if value else "Off"

    fmt = defn.get("display_fmt", "{}")
    unit = defn.get("unit", "")
    return fmt.format(value) + unit


def format_all_settings() -> str:
    """Return all settings as a formatted message."""
    lines = ["*Current settings*\n"]
    for key in ORDERED_KEYS:
        defn = SETTINGS_DEFS[key]
        lines.append(f"• {defn['label']}: {format_setting(key)}")
    return "\n".join(lines)
