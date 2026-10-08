"""Configuration for the virtual-coin Telegram casino bot."""
import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).with_name("casino.sqlite3")))
STARTING_BALANCE = int(os.getenv("STARTING_BALANCE", "1000"))
DAILY_REWARD = int(os.getenv("DAILY_REWARD", "250"))
WEEKLY_REWARD = int(os.getenv("WEEKLY_REWARD", "1500"))
MAX_BET = int(os.getenv("MAX_BET", "100000"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "2"))
MAINTENANCE = os.getenv("MAINTENANCE", "false").lower() == "true"
