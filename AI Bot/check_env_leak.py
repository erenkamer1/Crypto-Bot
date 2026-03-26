"""
Checks whether sensitive environment variables are set locally.
Never prints actual values (safe for public repos).
"""
import os
from dotenv import load_dotenv


def _status(name: str) -> str:
    v = os.getenv(name)
    if v is None or v == "":
        return "empty"
    return "set"


def main():
    print("--- ENV CHECK (masked) ---")
    print(f"CWD: {os.getcwd()}")
    load_dotenv(".env", override=True)

    for key in (
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        print(f"{key}: {_status(key)}")


if __name__ == "__main__":
    main()
