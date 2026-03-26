"""
AI Bot 4 - Windows EXE build script (PyInstaller).
"""

import subprocess
import sys
import os


def install_requirements():
    """Install build dependencies."""
    print("Installing packages...")
    packages = [
        "pyinstaller",
        "customtkinter"
    ]
    for pkg in packages:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    print("Packages installed")


def build_exe():
    """Build single-file EXE."""
    print("Building EXE...")

    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "AIBot4",
        "--icon", "NONE",
        "--add-data", "models;models",
        "--hidden-import", "customtkinter",
        "--hidden-import", "ccxt",
        "--hidden-import", "pandas",
        "--hidden-import", "numpy",
        "--hidden-import", "sklearn",
        "--hidden-import", "xgboost",
        "--hidden-import", "joblib",
        "--hidden-import", "ta",
        "--collect-all", "customtkinter",
        "--collect-all", "xgboost",
        "gui_app.py"
    ]

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\nEXE built successfully.")
        print("Output: dist/AIBot4.exe")
    else:
        print("\nEXE build failed.")
        return False

    return True


def main():
    print("=" * 50)
    print("   AI Bot 4 - Windows EXE Builder")
    print("=" * 50)

    try:
        install_requirements()
    except Exception as e:
        print(f"Package install error: {e}")
        return

    build_exe()

    print("\nUsage:")
    print("   1. Run dist/AIBot4.exe")
    print("   2. Enter API key and secret")
    print("   3. Enter starting capital")
    print("   4. Click Start")
    print("\nTip: Run the exe from the bot folder so it finds models and config.")


if __name__ == "__main__":
    main()
