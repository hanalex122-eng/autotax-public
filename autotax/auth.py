import os
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Header, Cookie

logger = logging.getLogger("autotax")

SECRET = os.getenv("JWT_SECRET", "").strip()
if not SECRET:
    raise RuntimeError(
        "JWT_SECRET ortam degiskeni zorunludur. "
        "Uretmek icin: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if len(SECRET) < 32:
    raise RuntimeError("JWT_SECRET en az 32 karakter olmali.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60       # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 7          # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # iat (issued-at) — "Alle Geraete abmelden" sonrasi tokenlari
    # gecersiz kilmak icin User.jwt_invalidate_before ile karsilastirilir.
    payload = {"sub": user_id, "email": email, "iat": now, "exp": exp, "type": "access"}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def create_refresh_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "email": email, "iat": now, "exp": exp, "type": "refresh"}
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
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


def _check_global_invalidate(payload: dict) -> None:
    """Reject token if user.jwt_invalidate_before > token.iat.

    Triggered by POST /auth/logout-all. Adds one DB lookup per authenticated
    request — acceptable for an MVP; can be moved to Redis later.
    """
    iat = payload.get("iat")
    sub = payload.get("sub")
    if not iat or not sub:
        return  # legacy tokens without iat — let them through
    try:
        from autotax.db import SessionLocal
        from autotax.models import User
    except Exception:
        return
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == sub).first()
        if not u or not u.jwt_invalidate_before:
            return
        # iat is unix seconds; jwt_invalidate_before is timezone-aware datetime
        cutoff_ts = u.jwt_invalidate_before.replace(tzinfo=timezone.utc).timestamp() \
            if u.jwt_invalidate_before.tzinfo is None \
            else u.jwt_invalidate_before.timestamp()
        if iat < cutoff_ts:
            raise HTTPException(status_code=401, detail="Session beendet — bitte erneut anmelden")
    finally:
        db.close()


def _resolve_token(authorization: str | None, atx_token_cookie: str | None) -> str:
    """Sprint 1: HttpOnly cookie dual mode. Authorization header öncelik
    (mevcut frontend hala header gönderiyor), yoksa cookie'ye düş."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if atx_token_cookie:
        return atx_token_cookie
    raise HTTPException(status_code=401, detail="Missing or invalid token")


def get_current_user(
    authorization: str = Header(None),
    atx_token: str = Cookie(None),
) -> dict:
    token = _resolve_token(authorization, atx_token)
    payload = decode_token(token, expected_type="access")
    _check_global_invalidate(payload)
    return payload


def get_acting_context(
    authorization: str = Header(None),
    atx_token: str = Cookie(None),
    x_acting_client_id: str = Header(None),
) -> dict:
    """Returns the *effective* user context.

    If the caller passes the X-Acting-Client-Id header AND has an active
    AdvisorRelationship with that client, returns:
        { "sub": <client_id>, "email": <client_email>, "is_acting": True,
          "advisor_id": <real_user_id>, "scope": "read"|"read_export" }

    Otherwise behaves like get_current_user and adds is_acting=False so
    every endpoint can use a single dependency.
    """
    token = _resolve_token(authorization, atx_token)
    payload = decode_token(token, expected_type="access")
    _check_global_invalidate(payload)
    payload = dict(payload)
    payload["is_acting"] = False
    payload["scope"] = "owner"
    if not x_acting_client_id:
        return payload
    try:
        target_id = int(x_acting_client_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid X-Acting-Client-Id")
    if target_id == payload.get("sub"):
        return payload  # acting as self is a no-op
    try:
        from autotax.db import SessionLocal
        from autotax.models import User, AdvisorRelationship
    except Exception:
        raise HTTPException(status_code=500, detail="acting context unavailable")
    db = SessionLocal()
    try:
        rel = db.query(AdvisorRelationship).filter(
            AdvisorRelationship.advisor_user_id == payload["sub"],
            AdvisorRelationship.client_user_id == target_id,
            AdvisorRelationship.revoked_at.is_(None),
        ).first()
        if not rel:
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Mandanten")
        client = db.query(User).filter(User.id == target_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
        return {
            "sub": target_id,
            "email": client.email,
            "is_acting": True,
            "advisor_id": payload["sub"],
            "advisor_email": payload.get("email"),
            "scope": rel.scope,
        }
    finally:
        db.close()


def require_owner_or_export(ctx: dict, action: str = "write") -> None:
    """Guard for write endpoints. action='export' allows scope=read_export."""
    if not ctx.get("is_acting"):
        return  # real owner — anything goes
    scope = ctx.get("scope", "read")
    if action == "export" and scope == "read_export":
        return
    raise HTTPException(
        status_code=403,
        detail="Read-only Zugriff — als Steuerberater dürfen Sie keine Daten verändern."
    )


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
