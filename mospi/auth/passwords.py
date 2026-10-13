"""Password hashing (scrypt, standard library only), the password rules and temporary passwords.

Stored form: ``scrypt$<log2 N>$<r>$<p>$<salt>$<hash>`` with URL-safe base64 without padding (checked by the
``app_users`` table, so nothing else can be stored).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

LOG2_N, R, P = 14, 8, 1                    # 16 MiB and roughly 50 ms per hash on a laptop
MAX_MEMORY = 64 * 1024 * 1024
MIN_LENGTH, MAX_LENGTH = 12, 128
# Temporary passwords are read out or typed from a message: no characters that are easy to confuse (0/O, 1/l/I).
_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** LOG2_N, r=R, p=P, maxmem=MAX_MEMORY, dklen=32)
    return f"scrypt${LOG2_N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, log2_n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt" or not 10 <= int(log2_n) <= 20 or not 1 <= int(r) <= 32 or not 1 <= int(p) <= 16:
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=2 ** int(log2_n), r=int(r), p=int(p), maxmem=MAX_MEMORY,
                                dklen=len(_unb64(expected)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, _unb64(expected))


# Verified when the username does not exist, so an unknown name takes as long as a wrong password.
_DUMMY = hash_password(secrets.token_urlsafe(16))


def burn_time(password: str) -> None:
    verify_password(password, _DUMMY)


def password_problem(password: str, *, username: str = "", display_name: str = "") -> str | None:
    """Why a chosen password is refused, in plain words (None when it is acceptable)."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    if len(set(password)) < 5:
        return "Use a password with more variety; this one repeats too few characters."
    lowered = password.lower()
    for word in (username, *display_name.split()):
        if len(word) >= 3 and word.lower() in lowered:
            return "Do not include your name or username in the password."
    return None


def temporary_password() -> str:
    """Four groups of four, e.g. ``Kp7m-x9Qa-3rTe-Wn4b`` (about 92 bits)."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4))
