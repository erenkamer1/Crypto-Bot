"""
Path utilities for the AI Bot.
Resolves the correct base path for PyInstaller (frozen exe) and normal Python runs.
"""

import os
import sys


def get_base_dir():
    """
    Writable base directory for data files.
    - Frozen (exe): folder containing the executable
    - Normal: script directory (AI Bot/)
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir():
    """
    Read-only packaged data (e.g. models).
    - Frozen: PyInstaller extract dir (_MEIPASS)
    - Normal: script directory
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))
