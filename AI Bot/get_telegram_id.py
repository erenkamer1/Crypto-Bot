import requests
import time
import json

def get_chat_id():
    print("--- Telegram Chat ID helper ---")
    print("1. Paste the TOKEN you got from @BotFather below.")
    token = input("Token: ").strip()

    if not token:
        print("Token cannot be empty!")
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"

    print("\n2. Open Telegram, send 'Hello' to your bot.")
    print("After sending, press ENTER here...")
    input()

    print("Checking...")

    try:
        response = requests.get(url)
        data = response.json()

        if not data['ok']:
            print("Error: Invalid token or API error.")
            print(data)
            return

        results = data['result']

        if not results:
            print("No messages yet. Make sure you messaged the bot and try again.")
            return

        last_message = results[-1]
        chat_id = last_message['message']['chat']['id']
        username = last_message['message']['chat'].get('username', 'unknown')
        first_name = last_message['message']['chat'].get('first_name', 'unknown')

        print(f"\nOK!")
        print(f"User: {first_name} ({username})")
        print(f"Chat ID: {chat_id}")

        print(f"\nPut this in config / .env as TELEGRAM_CHAT_ID:")
        print(f'TELEGRAM_CHAT_ID = "{chat_id}"')

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_chat_id()
