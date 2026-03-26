"""
Daily file logging for the AI Bot.
Writes INFO/WARNING/ERROR/EXCEPTION to DD.MM.YYYY_logs.txt under logs/.
Keeps logs for 7 days.
"""

import logging
import os
import re
import sys
from datetime import datetime, timedelta

import path_utils

LOG_FILE_PATTERN = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})_logs\.txt$")
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_logging_initialized = False


def get_logs_dir():
    """Returns logs/ directory, creating it if needed."""
    logs_dir = os.path.join(path_utils.get_base_dir(), "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        pass
    return logs_dir


def get_daily_log_path():
    """Today's log file path as DD.MM.YYYY_logs.txt."""
    today = datetime.now().strftime("%d.%m.%Y")
    return os.path.join(get_logs_dir(), f"{today}_logs.txt")


def _parse_log_filename(filename):
    """Parses date from DD.MM.YYYY_logs.txt filename, or None if invalid."""
    m = LOG_FILE_PATTERN.match(filename)
    if not m:
        return None
    try:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(year, month, day).date()
    except (ValueError, TypeError):
        return None


def cleanup_old_logs(retention_days=7):
    """Deletes log files older than retention_days."""
    logs_dir = get_logs_dir()
    cutoff = datetime.now().date() - timedelta(days=retention_days)
    try:
        for name in os.listdir(logs_dir):
            if not name.endswith("_logs.txt"):
                continue
            file_date = _parse_log_filename(name)
            if file_date is not None and file_date < cutoff:
                path = os.path.join(logs_dir, name)
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def setup_logging():
    """Configures logging. Idempotent."""
    global _logging_initialized
    if _logging_initialized:
        return
    try:
        logs_dir = get_logs_dir()
        cleanup_old_logs(retention_days=7)
        log_path = get_daily_log_path()

        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        for h in root.handlers:
            if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("_logs.txt"):
                _logging_initialized = True
                return
        root.addHandler(file_handler)

        _original_excepthook = sys.excepthook

        def _excepthook(exc_type, exc_value, exc_tb):
            logger = logging.getLogger("app_logger")
            logger.exception(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_tb)
            )
            if _original_excepthook:
                _original_excepthook(exc_type, exc_value, exc_tb)

        sys.excepthook = _excepthook
        _logging_initialized = True
    except Exception:
        pass  # Logging failure must not stop the bot


def get_logger(name="aibot"):
    """Returns a logger for the given module name."""
    return logging.getLogger(name)
