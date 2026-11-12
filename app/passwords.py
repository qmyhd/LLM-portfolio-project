"""
Password-account helpers: username and password rules, argon2 hashing.

Passwords are never trimmed or otherwise altered anywhere: the exact string
the user typed is what gets hashed and verified.
"""

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 10
MIN_OWNER_PASSWORD = 14
MAX_PASSWORD = 128

_hasher = PasswordHasher()
# Verified against when no real hash exists, so the "no such user" path does
# the same argon2 work as the "wrong password" path.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-only")


def normalize_username(raw: str) -> str:
    """Trim and lower-case a username; raise ValueError if it breaks the rule."""
    name = (raw or "").strip().lower()
    if not USERNAME_RE.fullmatch(name):
        raise ValueError(
            "Username must be 3 to 32 characters: letters, numbers, dot, dash or underscore"
        )
    return name


def check_password_rules(password: str, role: str) -> None:
    """Raise ValueError naming the rule a new password breaks."""
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"Password must be at most {MAX_PASSWORD} characters")
    if not password.strip():
        raise ValueError("Password cannot be only spaces")
    minimum = MIN_OWNER_PASSWORD if role == "owner" else MIN_PASSWORD
    if len(password) < minimum:
        raise ValueError(f"Password must be at least {minimum} characters")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """
    Check a password against a stored hash. With no stored hash it still does
    one verification (against a dummy) and returns False, so timing doesn't
    reveal that the account is missing.
    """
    if stored_hash is None:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            pass
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
