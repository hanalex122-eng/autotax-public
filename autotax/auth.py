import os
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Header

logger = logging.getLogger("autotax")

SECRET = os.getenv("JWT_SECRET", "")
if not SECRET:
    import secrets as _s
    SECRET = _s.token_urlsafe(32)
    logger.critical("JWT_SECRET is not set! Using random secret. Tokens will NOT survive restart. Set JWT_SECRET in environment variables!")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60       # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 7          # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int, email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "email": email, "exp": exp, "type": "access"}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def create_refresh_token(user_id: int, email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "email": email, "exp": exp, "type": "refresh"}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def create_token(user_id: int, email: str) -> str:
    """Backward compatible — returns access token."""
    return create_access_token(user_id, email)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        data = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        if data.get("type") != expected_type:
            raise ValueError(f"Expected {expected_type} token")
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    return decode_token(authorization[7:], expected_type="access")


# --- ADDED START: Auth debugging helpers ---
logger.info("JWT_SECRET startup check: configured=%s, length=%d", bool(SECRET), len(SECRET))


def safe_verify_token(token: str) -> dict:
    """Safely decode token, catching all errors. Returns dict with status + details.
    Does NOT raise — always returns diagnostic info."""
    result = {"valid": False, "error": None, "decoded": None, "token_preview": ""}
    if not token:
        result["error"] = "empty_token"
        logger.warning("TOKEN_DEBUG: empty token received")
        return result
    result["token_preview"] = "***"  # DSGVO: don't log token content
    try:
        data = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        result["valid"] = True
        result["decoded"] = {
            "sub": data.get("sub"),
            "email": data.get("email"),
            "type": data.get("type"),
            "exp": data.get("exp"),
        }
        # Calculate expiration
        if data.get("exp"):
            exp_time = datetime.fromtimestamp(data["exp"], tz=timezone.utc)
            now = datetime.now(timezone.utc)
            remaining = (exp_time - now).total_seconds()
            result["decoded"]["expires_at"] = exp_time.isoformat()
            result["decoded"]["expires_in_seconds"] = int(remaining)
            result["decoded"]["is_expired"] = remaining <= 0
        logger.info("TOKEN_DEBUG: valid token, type=%s, exp_in=%ss",
                    data.get("type"),
                    result["decoded"].get("expires_in_seconds"))
        return result
    except jwt.ExpiredSignatureError:
        result["error"] = "expired"
        logger.warning("TOKEN_DEBUG: expired signature — token=%s", result["token_preview"])
        # Try to decode without verifying expiration to see the original data
        try:
            raw = jwt.decode(token, SECRET, algorithms=[ALGORITHM], options={"verify_exp": False})
            result["decoded"] = {"sub": raw.get("sub"), "email": raw.get("email"), "type": raw.get("type")}
        except Exception:
            pass
        return result
    except jwt.InvalidSignatureError:
        result["error"] = "invalid_signature"
        logger.warning("TOKEN_DEBUG: invalid signature — SECRET mismatch (restart?) — token=%s", result["token_preview"])
        return result
    except jwt.DecodeError as e:
        result["error"] = "decode_error: " + str(e)
        logger.warning("TOKEN_DEBUG: decode error: %s — token=%s", e, result["token_preview"])
        return result
    except jwt.InvalidTokenError as e:
        result["error"] = "invalid_token: " + str(e)
        logger.warning("TOKEN_DEBUG: invalid token: %s — token=%s", e, result["token_preview"])
        return result
    except Exception as e:
        result["error"] = "unexpected: " + str(e)
        logger.warning("TOKEN_DEBUG: unexpected error: %s — token=%s", e, result["token_preview"])
        return result


def log_refresh_attempt(token: str, result: str, reason: str = ""):
    """Log refresh token attempts for debugging."""
    preview = "***"  # DSGVO: don't log token content
    logger.info("REFRESH_DEBUG: %s — token=%s, reason=%s", result, preview, reason)
# --- ADDED END ---
