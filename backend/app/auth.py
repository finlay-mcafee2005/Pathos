"""
Password hashing utilities.
"""

import bcrypt


def hash_password(plain_password: str) -> str:
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )

# ---------------------------------------------------------------------------
# Login tokens
#
# After login/signup the backend hands the browser a signed token (a standard
# HS256 JWT). The browser sends it back on every request as
# "Authorization: Bearer <token>", and the backend only serves data for the
# user the token belongs to. Signed with AUTH_SECRET, so nobody can forge one
# for another user without the secret.
# ---------------------------------------------------------------------------

import base64
import hashlib
import hmac
import json
import os
import time
import warnings
from typing import Optional
from uuid import UUID

TOKEN_DAYS = 30
_DEV_SECRET = "dev-only-secret-change-me"
AUTH_SECRET = os.environ.get("AUTH_SECRET") or _DEV_SECRET
if AUTH_SECRET == _DEV_SECRET:
    warnings.warn("AUTH_SECRET is not set; using the dev secret. Set it in production.")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(msg: str) -> str:
    return _b64(hmac.new(AUTH_SECRET.encode(), msg.encode(), hashlib.sha256).digest())


def make_token(user_id: UUID) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    body = _b64(json.dumps({"sub": str(user_id), "iat": now,
                            "exp": now + TOKEN_DAYS * 86400}).encode())
    return f"{header}.{body}.{_sign(header + '.' + body)}"


def read_token(token: str) -> Optional[UUID]:
    """The user id inside a valid, unexpired token, else None."""
    try:
        header, body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(header + "." + body)):
            return None
        claims = json.loads(_unb64(body))
        if claims.get("exp", 0) < time.time() or "pur" in claims:
            return None
        return UUID(claims["sub"])
    except Exception:
        return None


# One-purpose links (email verification). Same signature as login tokens, but
# carry a "purpose" so a verify link can never be used as a login token, and
# the email it was sent to, so changing the email invalidates old links.

def make_link_token(user_id: UUID, purpose: str, email: str, hours: int = 24) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    body = _b64(json.dumps({"sub": str(user_id), "pur": purpose, "eml": email.lower(),
                            "iat": now, "exp": now + hours * 3600}).encode())
    return f"{header}.{body}.{_sign(header + '.' + body)}"


def read_link_token(token: str, purpose: str):
    """(user_id, email) from a valid, unexpired link of this purpose, else None."""
    try:
        header, body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(header + "." + body)):
            return None
        claims = json.loads(_unb64(body))
        if claims.get("pur") != purpose or claims.get("exp", 0) < time.time():
            return None
        return UUID(claims["sub"]), claims.get("eml", "")
    except Exception:
        return None
