import re
import datetime
from typing import Optional, List
import bcrypt
import jwt
from cryptography.fernet import Fernet
from elite_cloud.config import SECRET_KEY, FERNET_KEY, JWT_ALGORITHM, JWT_EXPIRATION_HOURS

_fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)

# Password hashing
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

# JWT Tokens
def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        return None

# Secret Encryption (Fernet)
def encrypt_secret(plain_text: str) -> str:
    if not plain_text:
        return ""
    encrypted = _fernet.encrypt(plain_text.encode("utf-8"))
    return encrypted.decode("utf-8")

def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        decrypted = _fernet.decrypt(cipher_text.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception:
        return "[ENCRYPTED_SECRET_CORRUPTED]"

# Secret Masking in Logs & Outputs
BOT_TOKEN_PATTERN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,45}\b")
BEARER_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
MONGO_PASS_PATTERN = re.compile(r"(mongodb(?:\+srv)?:\/\/[^:]+:)([^@]+)(@)", re.IGNORECASE)
GENERIC_SECRET_PATTERN = re.compile(r"((?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?)([^'\"\s&]+)(['\"]?)", re.IGNORECASE)

def mask_secrets(text: str, known_secrets: Optional[List[str]] = None) -> str:
    if not text:
        return text
    
    # Mask Telegram bot tokens
    masked = BOT_TOKEN_PATTERN.sub("[REDACTED_TELEGRAM_TOKEN]", text)
    
    # Mask Bearer tokens
    masked = BEARER_PATTERN.sub("Bearer [REDACTED_BEARER_TOKEN]", masked)
    
    # Mask MongoDB passwords in connection strings
    masked = MONGO_PASS_PATTERN.sub(r"\1[REDACTED_PASSWORD]\3", masked)
    
    # Mask generic key/token patterns
    masked = GENERIC_SECRET_PATTERN.sub(r"\1[REDACTED]\3", masked)
    
    # Mask explicitly provided known secrets (such as env var values)
    if known_secrets:
        for s in known_secrets:
            if s and len(s) >= 4 and s in masked:
                masked = masked.replace(s, "[REDACTED_SECRET]")
                
    return masked
