"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Database
DB_PATH = os.getenv("DB_PATH", "dealership.db")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
DEALER_NAME = os.getenv("DEALER_NAME", "our dealership")
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "").strip()

# Meta / WhatsApp Cloud API
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", os.getenv("VERIFY_TOKEN", "cronoa_meta_webhook_verify_token_2026"))
META_APP_SECRET = os.getenv("META_APP_SECRET", os.getenv("APP_SECRET", ""))
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", os.getenv("META_ACCESS_TOKEN", ""))
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", os.getenv("PHONE_NUMBER_ID", ""))
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
