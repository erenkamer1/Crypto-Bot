"""
Telegram command listener.
Modular handler registry. Call telegram_commands.check_for_commands() from the main loop.
"""
import os
import time
import requests
import config
import runtime_config
import telegram_bot
import config_manager
import telegram_wizard
from excel_creator import generate_excel_report, generate_ai_excel_report, parse_report_date


# === Pending state (specific /set_* commands) ===
_pending_set = {}
_pending_lock = __import__("threading").Lock()

PENDING_TIMEOUT = 120  # seconds


def _get_pending(chat_id: str):
    """Return pending /set reply state if any."""
    with _pending_lock:
        pending = _pending_set.get(chat_id)
        if pending and (time.time() - pending["timestamp"]) > PENDING_TIMEOUT:
            del _pending_set[chat_id]
            return None
        return pending


def _set_pending(chat_id: str, key: str):
    with _pending_lock:
        _pending_set[chat_id] = {"key": key, "timestamp": time.time()}


def _clear_pending(chat_id: str):
    with _pending_lock:
        _pending_set.pop(chat_id, None)


# === Pending Excel (report date filter) ===
_pending_excel = {}


def _get_pending_excel(chat_id: str):
    with _pending_lock:
        pending = _pending_excel.get(chat_id)
        if pending and (time.time() - pending["timestamp"]) > PENDING_TIMEOUT:
            del _pending_excel[chat_id]
            return None
        return pending


def _set_pending_excel(chat_id: str, report_type: str):
    with _pending_lock:
        _pending_excel[chat_id] = {"type": report_type, "timestamp": time.time()}


def _clear_pending_excel(chat_id: str):
    with _pending_lock:
        _pending_excel.pop(chat_id, None)


def send_document(filepath, caption=""):
    """Send a file to Telegram."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendDocument"

    with open(filepath, 'rb') as f:
        files = {'document': f}
        data = {
            'chat_id': config.TELEGRAM_CHAT_ID,
            'caption': caption
        }
        response = requests.post(url, files=files, data=data)

    return response.json()


def handle_help(chat_id, text):
    msg = (
        "📌 *AI Bot v2 commands*\n\n"
        "📊 *Reports:*\n"
        "/excel → Trade report\n"
        "/excelai → ML performance report\n\n"
        "⚙️ *Bot control:*\n"
        "/stop (or /durdur) → Stop taking new trades\n"
        "/resume (or /baslat) → Resume new trades\n\n"
        "📋 *Settings:*\n"
        "/settings (or /ayarlar) → Show current settings\n"
        "/settingswizard (or /ayarwizard) → Interactive settings wizard\n\n"
        "🔧 *Specific /set commands:*\n"
        "/set\\_ml → ML confidence threshold\n"
        "/set\\_tp1 → TP1 %\n"
        "/set\\_tp2 → TP2 %\n"
        "/set\\_sl → SL %\n"
        "/set\\_be → BE SL buffer\n"
        "/set\\_slbuffer → Initial SL buffer\n"
        "/set\\_usdt → USDT per trade\n"
        "/set\\_trade → Allow new trades on/off\n"
        "/set\\_balanceinfo → Balance info on/off"
    )
    telegram_bot.send_message(msg)
    print("/help handled")


EXCEL_DATE_PROMPT = (
    "📅 Enter report start date (e.g. 10.02.2026)\n"
    "Use '-' for all data."
)


def handle_excel(chat_id, text):
    _clear_pending(chat_id)
    telegram_bot.send_message(EXCEL_DATE_PROMPT)
    _set_pending_excel(chat_id, "excel")
    print("/excel — waiting for date")


def handle_excelai(chat_id, text):
    _clear_pending(chat_id)
    telegram_bot.send_message(EXCEL_DATE_PROMPT)
    _set_pending_excel(chat_id, "excelai")
    print("/excelai — waiting for date")


def handle_durdur(chat_id, text):
    print("/stop (or /durdur) — disabling new trades...")
    try:
        rc = runtime_config.get_config()
        rc.allow_new_trades = False
        rc.save_to_file()
        telegram_bot.send_message(
            "⛔ Bot paused — no new trades.\n"
            "📌 Open positions are unchanged.\n"
            "🔄 To resume: /resume or /baslat"
        )
        print("allow_new_trades = False")
    except Exception as e:
        print(f"/stop error: {e}")
        telegram_bot.send_message(f"❌ Pause error: {e}")


def handle_baslat(chat_id, text):
    print("/resume (or /baslat) — enabling new trades...")
    try:
        rc = runtime_config.get_config()
        rc.allow_new_trades = True
        rc.save_to_file()
        telegram_bot.send_message(
            "✅ Bot resumed — ready for new trades.\n"
            "📌 To pause: /stop or /durdur"
        )
        print("allow_new_trades = True")
    except Exception as e:
        print(f"/resume error: {e}")
        telegram_bot.send_message(f"❌ Resume error: {e}")


def handle_ayarlar(chat_id, text):
    print("/settings (or /ayarlar) received")
    try:
        msg = config_manager.format_all_settings()
        telegram_bot.send_message(msg)
    except Exception as e:
        print(f"/settings error: {e}")
        telegram_bot.send_message(f"❌ Settings list error: {e}")


def handle_ayarwizard(chat_id, text):
    print("/settingswizard (or /ayarwizard) received")
    try:
        _clear_pending(chat_id)
        telegram_wizard.start_wizard(chat_id)
    except Exception as e:
        print(f"/settingswizard error: {e}")
        telegram_bot.send_message(f"❌ Wizard error: {e}")


def handle_set(setting_key, chat_id, text):
    """Start a specific setting change flow."""
    _clear_pending_excel(chat_id)
    if telegram_wizard.is_wizard_active(chat_id):
        telegram_bot.send_message(
            "⚠️ Finish the wizard first or send /cancel (or /iptal)."
        )
        return

    defn = config_manager.SETTINGS_DEFS.get(setting_key)
    if not defn:
        telegram_bot.send_message(f"❌ Unknown setting: {setting_key}")
        return

    current = config_manager.format_setting(setting_key)
    label = defn["label"]

    if defn["type"] == bool:
        msg = (
            f"⚙️ *{label}*\n"
            f"Current: {current}\n\n"
            f"Enter new value:\n"
            f"✅ On: yes / on / true / 1\n"
            f"❌ Off: no / off / false / 0\n"
            f"↩️ Cancel: -"
        )
    else:
        unit = defn.get("unit", "")
        min_val = defn.get("min", "")
        max_val = defn.get("max", "")
        msg = (
            f"⚙️ *{label}*\n"
            f"Current: {current}\n\n"
            f"New value{unit}\n"
            f"(Min: {min_val}, Max: {max_val})\n"
            f"↩️ Cancel: -"
        )

    _set_pending(chat_id, setting_key)
    telegram_bot.send_message(msg)
    print(f"/set_{setting_key} — waiting for value")


def _handle_pending_input(chat_id: str, text: str) -> bool:
    """Handle reply to pending /set. Returns True if consumed."""
    pending = _get_pending(chat_id)
    if pending is None:
        return False

    key = pending["key"]
    defn = config_manager.SETTINGS_DEFS.get(key)
    if not defn:
        _clear_pending(chat_id)
        return False

    text = text.strip()

    if text == "-":
        _clear_pending(chat_id)
        telegram_bot.send_message(f"↩️ {defn['label']} change cancelled.")
        return True

    try:
        parsed = config_manager.validate_value(key, text)
        old_val = config_manager.format_setting(key)
        config_manager.set_setting(key, parsed)
        new_val = config_manager.format_setting(key)

        _clear_pending(chat_id)
        telegram_bot.send_message(
            f"✅ *{defn['label']}* updated!\n"
            f"Old: {old_val}\n"
            f"New: {new_val}"
        )
        print(f"{defn['label']} updated: {old_val} → {new_val}")
    except ValueError as e:
        telegram_bot.send_message(f"⚠️ {e}\nTry again or send '-' to cancel.")

    return True


def _handle_pending_excel(chat_id: str, text: str) -> bool:
    """Handle date reply for /excel. Returns True if consumed."""
    pending = _get_pending_excel(chat_id)
    if pending is None:
        return False

    report_type = pending["type"]

    try:
        start_date = parse_report_date(text)
    except ValueError as e:
        telegram_bot.send_message(f"⚠️ {e}")
        return True

    _clear_pending_excel(chat_id)

    if report_type == "excel":
        print("Date received, building signal report...")
        filepath, summary = generate_excel_report(start_date=start_date)
    else:
        print("Date received, building AI report...")
        filepath, summary = generate_ai_excel_report(start_date=start_date)

    if filepath:
        send_document(filepath, summary)
        try:
            os.remove(filepath)
        except Exception:
            pass
    else:
        telegram_bot.send_message(f"⚠️ {summary}")

    return True


COMMAND_HANDLERS = {
    "/help":           handle_help,
    "/excel":          handle_excel,
    "/excelai":        handle_excelai,
    "/durdur":         handle_durdur,
    "/stop":           handle_durdur,
    "/baslat":         handle_baslat,
    "/resume":         handle_baslat,
    "/ayarlar":        handle_ayarlar,
    "/settings":       handle_ayarlar,
    "/ayarwizard":     handle_ayarwizard,
    "/settingswizard": handle_ayarwizard,
    "/set_ml":         lambda cid, txt: handle_set("ml_threshold", cid, txt),
    "/set_tp1":        lambda cid, txt: handle_set("tp1_pct", cid, txt),
    "/set_tp2":        lambda cid, txt: handle_set("tp2_pct", cid, txt),
    "/set_sl":         lambda cid, txt: handle_set("sl_pct", cid, txt),
    "/set_be":         lambda cid, txt: handle_set("be_buffer_pct", cid, txt),
    "/set_slbuffer":   lambda cid, txt: handle_set("sl_buffer_pct", cid, txt),
    "/set_usdt":       lambda cid, txt: handle_set("fixed_trade_amount_usdt", cid, txt),
    "/set_trade":      lambda cid, txt: handle_set("allow_new_trades", cid, txt),
    "/set_balanceinfo": lambda cid, txt: handle_set("show_balance_info", cid, txt),
}


def check_for_commands():
    """Poll Telegram updates and dispatch commands."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"

    try:
        response = requests.get(url, params={"limit": 10, "timeout": 1})
        data = response.json()

        if not data.get("ok") or not data.get("result"):
            return False

        for update in data["result"]:
            message = update.get("message", {})
            text = message.get("text", "").strip()
            chat_id = str(message.get("chat", {}).get("id", ""))

            if chat_id != str(config.TELEGRAM_CHAT_ID):
                continue

            if not text:
                update_id = update.get("update_id")
                requests.get(url, params={"offset": update_id + 1})
                continue

            text_lower = text.lower()

            if telegram_wizard.is_wizard_active(chat_id):
                session = telegram_wizard.get_manager().get_session(chat_id)
                if session and session.current_key == "__confirm__":
                    telegram_wizard.handle_confirmation(chat_id, text)
                else:
                    if text_lower.startswith("/") and text_lower not in ("/iptal", "/cancel"):
                        telegram_bot.send_message(
                            "⚠️ Wizard active. Finish or send /cancel (or /iptal)."
                        )
                    else:
                        telegram_wizard.handle_wizard_input(chat_id, text)

                update_id = update.get("update_id")
                requests.get(url, params={"offset": update_id + 1})
                return True

            if not text_lower.startswith("/"):
                if _handle_pending_excel(chat_id, text):
                    update_id = update.get("update_id")
                    requests.get(url, params={"offset": update_id + 1})
                    return True
                if _handle_pending_input(chat_id, text):
                    update_id = update.get("update_id")
                    requests.get(url, params={"offset": update_id + 1})
                    return True

            handler = COMMAND_HANDLERS.get(text_lower)
            if handler:
                try:
                    handler(chat_id, text)
                except Exception as e:
                    print(f"Command error ({text_lower}): {e}")
                    telegram_bot.send_message(f"❌ Command error: {e}")

                update_id = update.get("update_id")
                requests.get(url, params={"offset": update_id + 1})
                return True

        return False

    except Exception as e:
        print(f"Command poll error: {e}")
        return False


if __name__ == "__main__":
    print("Telegram command listener test")
    print("=" * 40)

    print("\n[TEST 1] Signal history report")
    filepath, summary = generate_excel_report()
    if filepath:
        print(summary)
        print(f"File: {filepath}")
    else:
        print(f"⚠️ {summary}")

    print("\n[TEST 2] AI performance report")
    filepath_ai, summary_ai = generate_ai_excel_report()
    if filepath_ai:
        print(summary_ai)
        print(f"File: {filepath_ai}")
    else:
        print(f"⚠️ {summary_ai}")
