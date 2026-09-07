import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWITTERAPIS_API_KEY = os.getenv("TWITTERAPIS_API_KEY", "")

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
MIN_REPLY_CHARS = int(os.getenv("MIN_REPLY_CHARS", "15"))
MAX_REPLY_CHARS = int(os.getenv("MAX_REPLY_CHARS", "20"))
MAX_REPLIES_PER_USER_PER_DAY = int(os.getenv("MAX_REPLIES_PER_USER_PER_DAY", "1"))
AUTO_REPLY = os.getenv("AUTO_REPLY", "false").lower() == "true"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
