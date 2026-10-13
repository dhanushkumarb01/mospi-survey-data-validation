"""Signed session cookies.

The cookie holds ``<user id>.<session version>.<expiry>.<HMAC-SHA256>`` and nothing else: the role, name and active flag
are read from the account on each request, so a role change or deactivation applies at once, and raising the account's
session version (password set, account changed) ends every session it has.  HttpOnly, SameSite=Strict, and Secure on
HTTPS; JavaScript never sees it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time

COOKIE = "mospi_session"
LIFETIME_SECONDS = 10 * 3600            # one working day; signing in again after that is expected
MIN_SECRET_LENGTH = 32
LOG = logging.getLogger("MoSPI.auth")


class SessionSigner:
    def __init__(self, secret: str, lifetime: int = LIFETIME_SECONDS) -> None:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"The session secret must have at least {MIN_SECRET_LENGTH} characters.")
        self._key = hashlib.sha256(b"mospi-session:" + secret.encode("utf-8")).digest()
        self.lifetime = lifetime

    def _sign(self, payload: str) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()).rstrip(b"=").decode("ascii")

    def issue(self, user_id: int, version: int, now: float | None = None) -> str:
        payload = f"{int(user_id)}.{int(version)}.{int((now or time.time()) + self.lifetime)}"
        return f"{payload}.{self._sign(payload)}"

    def read(self, token: str | None, now: float | None = None) -> tuple[int, int] | None:
        """(user id, session version) of a valid, unexpired cookie; None otherwise."""
        if not token or len(token) > 200:
            return None
        payload, _, signature = token.rpartition(".")
        if not payload or not hmac.compare_digest(signature, self._sign(payload)):
            return None
        try:
            user_id, version, expires = (int(part) for part in payload.split("."))
        except ValueError:
            return None
        return (user_id, version) if expires > (now or time.time()) else None


def signer_from_env(*, required: bool) -> SessionSigner | None:
    """``MOSPI_SESSION_SECRET``.  Without it a local instance uses a random secret (sessions end when it restarts);
    an instance that must share sessions between processes (hosted) gets None and refuses sign-in plainly."""
    secret = os.environ.get("MOSPI_SESSION_SECRET", "").strip()
    if secret:
        try:
            return SessionSigner(secret)
        except ValueError:
            LOG.error("MOSPI_SESSION_SECRET is shorter than %d characters; it is not used.", MIN_SECRET_LENGTH)
            if required:
                return None
    elif required:
        return None
    return SessionSigner(secrets.token_urlsafe(48))
