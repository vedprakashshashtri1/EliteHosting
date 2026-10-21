import os
import sys
import time
import signal
import argparse
import subprocess
import threading
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from elite_cloud.config import (
    PYTHON_BIN, API_HOST, API_PORT, STREAMLIT_PORT,
    TELEGRAM_BOT_TOKEN
)

def run_api():
    print(f"🚀 Starting Elite Cloud Backend API on http://{API_HOST}:{API_PORT}...")
    import uvicorn
    uvicorn.run("elite_cloud.api.main:app", host=API_HOST, port=API_PORT, reload=False, log_level="info")

def run_dashboard():
    print(f"⚡ Starting Elite Cloud Streamlit Dashboard on port {STREAMLIT_PORT}...")
    dash_app = BASE_DIR / "dashboard" / "app.py"
    cmd = [
        PYTHON_BIN, "-m", "streamlit", "run",
        str(dash_app),
        "--server.port", str(STREAMLIT_PORT),
        "--server.headless", "true",
        "--theme.base", "dark"
    ]
    subprocess.run(cmd)

def run_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        print("ℹ️ TELEGRAM_BOT_TOKEN not configured in environment. Skipping Telegram bot runner.")
        return
    print("🤖 Starting Elite Cloud Telegram Management Bot...")
    from elite_cloud.telegram_bot.bot import create_telegram_bot
    bot_app = create_telegram_bot()
    if bot_app:
        bot_app.run_polling()

def main():
    parser = argparse.ArgumentParser(description="Elite Cloud Hosting - Master Platform Launcher")
    parser.add_argument("--service", choices=["all", "api", "dashboard", "bot"], default="all", help="Service to run")
    args = parser.parse_args()

    print("=" * 65)
    print("⚡ ELITE CLOUD HOSTING - PRODUCTION CLOUD MANAGEMENT PLATFORM")
    print("=" * 65)

    if args.service == "api":
        run_api()
    elif args.service == "dashboard":
        run_dashboard()
    elif args.service == "bot":
        run_telegram_bot()
    elif args.service == "all":
        threads = []
        # API Thread
        t_api = threading.Thread(target=run_api, daemon=True)
        t_api.start()
        threads.append(t_api)

        time.sleep(1.5)

        # Telegram Bot Thread
        if TELEGRAM_BOT_TOKEN:
            t_bot = threading.Thread(target=run_telegram_bot, daemon=True)
            t_bot.start()
            threads.append(t_bot)

        # Streamlit Dashboard in main thread
        try:
            run_dashboard()
        except KeyboardInterrupt:
            print("\n🛑 Shutting down Elite Cloud platform gracefully...")
            sys.exit(0)

if __name__ == "__main__":
    main()
