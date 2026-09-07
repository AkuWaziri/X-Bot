import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWITTERAPIS_API_KEY = os.getenv("TWITTERAPIS_API_KEY", "")
TWITTERAPIS_X_AUTH_TOKEN = os.getenv("TWITTERAPIS_X_AUTH_TOKEN", "")
TWITTERAPIS_CT0 = os.getenv("TWITTERAPIS_CT0", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
MIN_REPLY_CHARS = int(os.getenv("MIN_REPLY_CHARS", "10"))
MAX_REPLY_CHARS = int(os.getenv("MAX_REPLY_CHARS", "100"))
MAX_REPLIES_PER_USER_PER_DAY = int(os.getenv("MAX_REPLIES_PER_USER_PER_DAY", "1"))
AUTO_REPLY = os.getenv("AUTO_REPLY", "false").lower() == "true"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
