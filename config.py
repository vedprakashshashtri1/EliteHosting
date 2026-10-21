import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

# Base directories
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
WORKSPACES_DIR = DATA_DIR / "workspaces"
LOGS_DIR = DATA_DIR / "logs"
UPLOADS_DIR = DATA_DIR / "uploads"
TEMP_DIR = DATA_DIR / "temp"

for directory in (DATA_DIR, WORKSPACES_DIR, LOGS_DIR, UPLOADS_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Environment variables & secrets
def get_config_val(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default

def _get_or_create_secret(env_var: str, generator) -> str:
    val = get_config_val(env_var)
    if not val:
        val = generator()
    return val

SECRET_KEY = _get_or_create_secret("SECRET_KEY", lambda: secrets.token_hex(32))
FERNET_KEY = _get_or_create_secret("FERNET_KEY", lambda: Fernet.generate_key().decode())
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(get_config_val("JWT_EXPIRATION_HOURS", "72"))

# Database Configuration
MONGO_URI = get_config_val("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = get_config_val("MONGO_DB_NAME", "elite_cloud")

# Network & Host Configuration
API_HOST = get_config_val("API_HOST", "0.0.0.0")
API_PORT = int(get_config_val("API_PORT", "8000"))
API_URL = get_config_val("API_URL", f"http://localhost:{API_PORT}")
STREAMLIT_PORT = int(get_config_val("STREAMLIT_PORT", "8501"))
BASE_DOMAIN = get_config_val("BASE_DOMAIN", "apps.local")
APP_PORT_MIN = int(get_config_val("APP_PORT_MIN", "8100"))
APP_PORT_MAX = int(get_config_val("APP_PORT_MAX", "8900"))

# Telegram Bot
TELEGRAM_BOT_TOKEN = get_config_val("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = get_config_val("TELEGRAM_BOT_USERNAME", "EliteCloudManagerBot")

# Limits & Quotas
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100"))
MAX_EXTRACTED_SIZE_MB = int(os.getenv("MAX_EXTRACTED_SIZE_MB", "500"))
MAX_FILES_PER_ZIP = int(os.getenv("MAX_FILES_PER_ZIP", "5000"))
MAX_CONCURRENT_DEPLOYMENTS = int(os.getenv("MAX_CONCURRENT_DEPLOYMENTS", "20"))
DEFAULT_APP_RAM_LIMIT_MB = int(os.getenv("DEFAULT_APP_RAM_LIMIT_MB", "512"))
DEFAULT_APP_CPU_LIMIT_PCT = float(os.getenv("DEFAULT_APP_CPU_LIMIT_PCT", "100.0"))

# Executable auto-discovery
def get_python_executable() -> str:
    custom = os.getenv("PYTHON_EXECUTABLE")
    if custom and Path(custom).exists():
        return custom
    # Check local portable python
    local_embed = PROJECT_ROOT / ".python311" / "python.exe"
    if local_embed.exists():
        return str(local_embed)
    import sys
    return sys.executable

def get_node_executable() -> str:
    custom = os.getenv("NODE_EXECUTABLE")
    if custom and Path(custom).exists():
        return custom
    # Check common locations
    candidates = [
        "node",
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "node"

PYTHON_BIN = get_python_executable()
NODE_BIN = get_node_executable()
