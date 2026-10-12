"""Request signing shared by the gateway and its client (HMAC-SHA256 over method, exact path, time and a nonce).

Headers: ``X-MoSPI-Timestamp`` (Unix seconds), ``X-MoSPI-Nonce`` (32 hex), ``X-MoSPI-Signature`` (hex).
A request is accepted only within ``MAX_SKEW_SECONDS`` of the gateway clock and only once per nonce, so a captured
request cannot be replayed later.  The secret (``MOSPI_GATEWAY_SECRET``) never travels; it is at least 32 characters.
``MOSPI_GATEWAY_SECRET_PREVIOUS`` is also accepted by the gateway while a secret is being rotated.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time

MAX_SKEW_SECONDS = 120
MIN_SECRET_LENGTH = 32
# Run and case identifiers accepted in gateway paths (run directories and case ids are of this form).
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,199}$")
TIMESTAMP, NONCE, SIGNATURE = "x-mospi-timestamp", "x-mospi-nonce", "x-mospi-signature"


class SigningError(ValueError):
    pass


def configured_secret(variable: str = "MOSPI_GATEWAY_SECRET") -> str:
    value = os.environ.get(variable, "").strip()
    if len(value) < MIN_SECRET_LENGTH:
        raise SigningError(f"{variable} must be set to a random value of at least {MIN_SECRET_LENGTH} characters "
                           "(python -m mospi.gateway secret).")
    return value


def _message(method: str, path: str, timestamp: str, nonce: str) -> bytes:
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}".encode("utf-8")


def signature(secret: str, method: str, path: str, timestamp: str, nonce: str) -> str:
    return hmac.new(secret.encode("utf-8"), _message(method, path, timestamp, nonce), hashlib.sha256).hexdigest()


def sign(secret: str, method: str, path: str, *, now: float | None = None) -> dict[str, str]:
    """Headers for one request; ``path`` is the exact request target (path plus ``?query`` if any)."""
    timestamp, nonce = str(int(now if now is not None else time.time())), secrets.token_hex(16)
    return {TIMESTAMP: timestamp, NONCE: nonce, SIGNATURE: signature(secret, method, path, timestamp, nonce)}


class Verifier:
    """Checks signatures, the time window and nonce reuse (in memory; the window bounds how long nonces are kept)."""

    def __init__(self, secrets_: list[str], *, max_skew: int = MAX_SKEW_SECONDS, max_nonces: int = 100_000) -> None:
        self._secrets = [s for s in secrets_ if s]
        if not self._secrets:
            raise SigningError("No gateway secret is configured.")
        self.max_skew, self.max_nonces = max_skew, max_nonces
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def verify(self, method: str, path: str, headers: dict[str, str], *, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        timestamp, nonce, given = headers.get(TIMESTAMP, ""), headers.get(NONCE, ""), headers.get(SIGNATURE, "")
        if not (timestamp.isdigit() and len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce) and len(given) == 64):
            raise SigningError("missing or malformed signature headers")
        if abs(now - int(timestamp)) > self.max_skew:
            raise SigningError("request time outside the accepted window")
        if not any(hmac.compare_digest(signature(s, method, path, timestamp, nonce), given.lower()) for s in self._secrets):
            raise SigningError("bad signature")
        with self._lock:
            if nonce in self._seen:
                raise SigningError("replayed request")
            if len(self._seen) >= self.max_nonces:
                self._seen = {n: t for n, t in self._seen.items() if t > now}
                if len(self._seen) >= self.max_nonces:
                    raise SigningError("too many requests in the time window")
            self._seen[nonce] = now + 2 * self.max_skew
