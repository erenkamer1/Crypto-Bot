"""
Telegram settings wizard — interactive Q&A flow.
Thread-safe sessions with timeout per chat.
"""

import threading
import time
from datetime import datetime

import config_manager
import telegram_bot

WIZARD_TIMEOUT = 300  # seconds

NUM_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]


class WizardSession:
    """Wizard state for one chat."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        self.created_at = datetime.now()
        self.current_step = 0
        self.collected_values = {}
        self.waiting_for_manual = False
        self.current_key = None

    def is_expired(self) -> bool:
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > WIZARD_TIMEOUT


class WizardManager:
    """Thread-safe session store."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, WizardSession] = {}

    def has_active_session(self, chat_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(chat_id)
            if session is None:
                return False
            if session.is_expired():
                del self._sessions[chat_id]
                return False
            return True

    def start_session(self, chat_id: str) -> WizardSession:
        with self._lock:
            session = WizardSession(chat_id)
            self._sessions[chat_id] = session
            return session

    def get_session(self, chat_id: str):
        with self._lock:
            session = self._sessions.get(chat_id)
            if session and session.is_expired():
                del self._sessions[chat_id]
                return None
            return session

    def end_session(self, chat_id: str):
        with self._lock:
            self._sessions.pop(chat_id, None)


_manager = WizardManager()


def get_manager() -> WizardManager:
    return _manager


def is_wizard_active(chat_id: str) -> bool:
    return _manager.has_active_session(chat_id)


def start_wizard(chat_id: str):
    session = _manager.start_session(chat_id)
    print(f"Wizard started (chat_id: {chat_id})")

    telegram_bot.send_message(
        "🧙 *Settings wizard started*\n\n"
        "You will review each setting in order.\n"
        "At each step you see the current value and can change it.\n"
        "⏱ Timeout: 5 minutes\n\n"
        "Cancel: /cancel (or /iptal)"
    )
    time.sleep(0.3)
    _send_current_question(session)


def handle_wizard_input(chat_id: str, text: str) -> bool:
    """
    Process a message while wizard is active.
    Returns True if the message was consumed.
    """
    session = _manager.get_session(chat_id)
    if session is None:
        return False

    text = text.strip()

    if text.lower() in ("/iptal", "/cancel"):
        _manager.end_session(chat_id)
        telegram_bot.send_message("❌ Wizard cancelled.")
        print("Wizard cancelled.")
        return True

    keys = config_manager.ORDERED_KEYS

    if session.waiting_for_manual:
        return _handle_manual_input(session, text)

    return _handle_option_selection(session, text)


def _send_current_question(session: WizardSession):
    keys = config_manager.ORDERED_KEYS

    if session.current_step >= len(keys):
        _send_summary(session)
        return

    key = keys[session.current_step]
    defn = config_manager.SETTINGS_DEFS[key]
    current_value = config_manager.format_setting(key)
    session.current_key = key

    step_num = session.current_step + 1
    total = len(keys)

    if defn["type"] == bool:
        msg = (
            f"*[{step_num}/{total}] {defn['label']}*\n"
            f"Current: {current_value}\n\n"
            f"1️⃣ On\n"
            f"2️⃣ Off\n"
            f"3️⃣ Skip"
        )
        session.waiting_for_manual = False
    else:
        options = defn.get("wizard_options", [])
        lines = [
            f"*[{step_num}/{total}] {defn['label']}*",
            f"Current: {current_value}\n",
            "Pick a new value:"
        ]
        for i, opt in enumerate(options):
            unit = defn.get("unit", "")
            lines.append(f"{NUM_EMOJIS[i]} {opt}{unit}")
        lines.append(f"{NUM_EMOJIS[len(options)]} Enter manually")
        lines.append(f"{NUM_EMOJIS[len(options) + 1]} Skip")
        msg = "\n".join(lines)
        session.waiting_for_manual = False

    telegram_bot.send_message(msg)


def _handle_option_selection(session: WizardSession, text: str) -> bool:
    key = session.current_key
    if key is None:
        return True

    defn = config_manager.SETTINGS_DEFS[key]

    selection = _parse_selection(text)
    if selection is None:
        telegram_bot.send_message("⚠️ Invalid choice. Enter a number.")
        return True

    if defn["type"] == bool:
        if selection == 1:
            session.collected_values[key] = True
        elif selection == 2:
            session.collected_values[key] = False
        elif selection == 3:
            pass
        else:
            telegram_bot.send_message("⚠️ Enter 1, 2, or 3.")
            return True
    else:
        options = defn.get("wizard_options", [])
        max_option = len(options) + 2

        if selection < 1 or selection > max_option:
            telegram_bot.send_message(f"⚠️ Enter a number between 1 and {max_option}.")
            return True

        if selection <= len(options):
            try:
                parsed = config_manager.validate_value(key, options[selection - 1])
                session.collected_values[key] = parsed
            except ValueError as e:
                telegram_bot.send_message(f"⚠️ {e}")
                return True
        elif selection == len(options) + 1:
            session.waiting_for_manual = True
            unit = defn.get("unit", "")
            min_val = defn.get("min", "")
            max_val = defn.get("max", "")
            telegram_bot.send_message(
                f"✏️ Enter new value for *{defn['label']}*{unit}\n"
                f"(Min: {min_val}, Max: {max_val})\n"
                f"Cancel: -"
            )
            return True
        else:
            pass

    session.current_step += 1
    time.sleep(0.3)
    _send_current_question(session)
    return True


def _handle_manual_input(session: WizardSession, text: str) -> bool:
    key = session.current_key

    if text == "-":
        session.waiting_for_manual = False
        telegram_bot.send_message(f"↩️ Skipped {config_manager.SETTINGS_DEFS[key]['label']}.")
        session.current_step += 1
        time.sleep(0.3)
        _send_current_question(session)
        return True

    try:
        parsed = config_manager.validate_value(key, text)
        session.collected_values[key] = parsed
        session.waiting_for_manual = False
        session.current_step += 1
        time.sleep(0.3)
        _send_current_question(session)
    except ValueError as e:
        telegram_bot.send_message(f"⚠️ {e}\nTry again or '-' to skip.")

    return True


def _send_summary(session: WizardSession):
    if not session.collected_values:
        _manager.end_session(session.chat_id)
        telegram_bot.send_message("ℹ️ No changes. Wizard closed.")
        return

    lines = ["📋 *Change summary*\n"]
    for key, new_val in session.collected_values.items():
        defn = config_manager.SETTINGS_DEFS[key]
        old_val = config_manager.format_setting(key)

        if defn["type"] == bool:
            new_display = "On" if new_val else "Off"
        else:
            unit = defn.get("unit", "")
            fmt = defn.get("display_fmt", "{}")
            new_display = fmt.format(new_val) + unit

        lines.append(f"• {defn['label']}: {old_val} → {new_display}")

    lines.append("\n1️⃣ 🟢 Save")
    lines.append("2️⃣ 🔴 Cancel")

    session.current_key = "__confirm__"
    session.waiting_for_manual = False

    telegram_bot.send_message("\n".join(lines))


def handle_confirmation(chat_id: str, text: str) -> bool:
    session = _manager.get_session(chat_id)
    if session is None or session.current_key != "__confirm__":
        return False

    selection = _parse_selection(text)

    if selection == 1:
        try:
            for key, value in session.collected_values.items():
                config_manager.set_setting(key, value)

            _manager.end_session(chat_id)
            telegram_bot.send_message(
                f"✅ *{len(session.collected_values)} settings saved!*\n\n"
                f"View current settings: /settings (or /ayarlar)"
            )
            print(f"Wizard done — {len(session.collected_values)} settings updated")
        except Exception as e:
            telegram_bot.send_message(f"❌ Save error: {e}")
            print(f"Wizard save error: {e}")
        return True

    elif selection == 2:
        _manager.end_session(chat_id)
        telegram_bot.send_message("❌ Changes discarded.")
        print("Wizard changes discarded")
        return True

    else:
        telegram_bot.send_message("⚠️ Enter 1 (Save) or 2 (Cancel).")
        return True


def _parse_selection(text: str):
    text = text.strip()

    emoji_map = {
        "1️⃣": 1, "2️⃣": 2, "3️⃣": 3,
        "4️⃣": 4, "5️⃣": 5, "6️⃣": 6,
        "7️⃣": 7, "8️⃣": 8, "9️⃣": 9,
    }
    if text in emoji_map:
        return emoji_map[text]

    try:
        return int(text)
    except (ValueError, TypeError):
        return None
