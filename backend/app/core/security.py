"""Security primitives: rate limiting, API-key auth, upload validation.

The system has no user accounts, so authentication is a single shared API key
supplied in the ``X-API-Key`` header (or as a bearer token). JWT helpers are
kept for deployments that front the API with their own identity provider.
"""

from __future__ import annotations

import os
import re
import secrets
import time
import unicodedata
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, Request, status

from .config import settings
from .logger import get_application_logger

logger = get_application_logger("security")

#: Header carrying the shared API key.
API_KEY_HEADER = "X-API-Key"


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
@dataclass
class _Window:
    """Sliding window of request timestamps for one client."""

    hits: deque[float] = field(default_factory=deque)


class SlidingWindowRateLimiter:
    """In-process sliding-window rate limiter.

    A sliding window avoids the burst-at-the-boundary flaw of fixed windows: a
    client cannot send ``2 * limit`` requests by straddling a window edge.

    This is per-process state. Behind multiple workers each process enforces its
    own share of the limit; put a shared limiter (Redis, or the reverse proxy)
    in front for a strict global cap.
    """

    def __init__(self, max_tracked_clients: int = 10_000) -> None:
        self._windows: dict[str, _Window] = {}
        self._max_tracked_clients = max_tracked_clients

    def check(self, identifier: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Record a hit and report ``(allowed, seconds_until_retry)``."""
        now = time.monotonic()
        cutoff = now - window_seconds

        window = self._windows.get(identifier)
        if window is None:
            if len(self._windows) >= self._max_tracked_clients:
                self._evict_stale(cutoff)
            window = self._windows.setdefault(identifier, _Window())

        hits = window.hits
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(1, int(hits[0] + window_seconds - now) + 1)
            return False, retry_after

        hits.append(now)
        return True, 0

    def _evict_stale(self, cutoff: float) -> None:
        """Drop clients with no recent activity so the map cannot grow forever."""
        stale = [key for key, window in self._windows.items() if not window.hits or window.hits[-1] <= cutoff]
        for key in stale:
            del self._windows[key]
        if not stale:
            # Everything is active: drop the oldest half rather than leak.
            ordered = sorted(self._windows.items(), key=lambda item: item[1].hits[-1])
            for key, _ in ordered[: len(ordered) // 2]:
                del self._windows[key]

    def reset(self) -> None:
        self._windows.clear()


rate_limiter = SlidingWindowRateLimiter()


# --------------------------------------------------------------------------- #
# Client identification
# --------------------------------------------------------------------------- #
def get_client_ip(request: Request) -> str:
    """Best-effort client IP, honouring reverse-proxy headers.

    ``X-Forwarded-For`` is trusted only because this service is expected to sit
    behind a proxy that sets it. If yours does not, strip the header at the
    edge, otherwise clients can spoof their identity to dodge rate limits.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, limit: int, window_seconds: int = 60) -> None:
    """Raise 429 when the caller has exhausted its allowance."""
    identifier = get_client_ip(request)
    allowed, retry_after = rate_limiter.check(identifier, limit, window_seconds)
    if not allowed:
        logger.warning("Rate limit exceeded for %s on %s", identifier, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down and retry shortly.",
            headers={"Retry-After": str(retry_after)},
        )


# --------------------------------------------------------------------------- #
# API key authentication
# --------------------------------------------------------------------------- #
def extract_api_key(request: Request) -> str | None:
    """Read the API key from ``X-API-Key`` or an ``Authorization: Bearer`` header."""
    header_key = request.headers.get(API_KEY_HEADER)
    if header_key:
        return header_key.strip()

    authorization = request.headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip()

    return None


def require_api_key(request: Request) -> None:
    """Authorise a state-changing request.

    When ``TRAFFIC_API_KEY`` is unset the API is open -- convenient for local
    demos, and refused outright in production by ``validate_configuration``.
    """
    expected = settings.api_key
    if not expected:
        return

    provided = extract_api_key(request)
    if not provided or not secrets.compare_digest(provided, expected):
        log_security_event(
            "invalid_api_key",
            get_client_ip(request),
            {"path": request.url.path, "method": request.method},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"A valid {API_KEY_HEADER} header is required for this endpoint.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --------------------------------------------------------------------------- #
# JWT helpers (optional; for deployments with an external IdP)
# --------------------------------------------------------------------------- #
def create_access_token(claims: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Mint a signed JWT."""
    payload = dict(claims)
    expiry = datetime.now(UTC) + (expires_delta or timedelta(hours=settings.jwt_expiration_hours))
    payload["exp"] = expiry
    payload.setdefault("iat", datetime.now(UTC))
    return jwt.encode(payload, settings.resolved_jwt_secret(), algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, Any] | None:
    """Validate a JWT, returning its claims or ``None`` when invalid."""
    try:
        return jwt.decode(token, settings.resolved_jwt_secret(), algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as error:
        logger.warning("JWT verification failed: %s", error)
        return None


# --------------------------------------------------------------------------- #
# Upload hardening
# --------------------------------------------------------------------------- #
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_LEADING_DOTS = re.compile(r"^\.+")


def sanitize_filename(filename: str | None) -> str:
    """Reduce an uploaded filename to a safe basename.

    Strips directory components, normalises Unicode (so look-alike characters
    cannot smuggle separators through), replaces anything outside a strict
    allowlist and guarantees a non-empty result.
    """
    if not filename:
        return f"upload_{secrets.token_hex(8)}"

    # Normalise first: NFKC folds e.g. fullwidth solidus into '/'.
    normalised = unicodedata.normalize("NFKC", filename)
    # Cut on both separators; os.path.basename alone misses '\' on POSIX.
    basename = os.path.basename(normalised.replace("\\", "/"))
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", basename)
    cleaned = _LEADING_DOTS.sub("", cleaned)[:180]

    if not cleaned or cleaned in {"_", "."}:
        return f"upload_{secrets.token_hex(8)}"
    return cleaned


def file_extension(filename: str | None) -> str:
    """Lowercase extension including the dot, or ``''`` when there is none."""
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def validate_file_type(filename: str | None, allowed_extensions: Iterable[str]) -> bool:
    """Whether ``filename`` carries one of ``allowed_extensions``."""
    extension = file_extension(filename)
    if not extension:
        return False
    allowed = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_extensions}
    return extension in allowed


def generate_secure_filename(original_filename: str | None) -> str:
    """Collision-resistant name that preserves the original extension."""
    safe = sanitize_filename(original_filename)
    stem, _, extension = safe.rpartition(".")
    if not stem:
        stem, extension = safe, ""
    suffix = f".{extension}" if extension else ""
    return f"{stem[:80]}_{int(time.time())}_{secrets.token_hex(4)}{suffix}"


#: Leading bytes that identify the image formats we accept. Checking these stops
#: a renamed executable (or a polyglot) from being processed as an image.
_IMAGE_MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"BM", "bmp"),
    (b"RIFF", "webp"),
)


def looks_like_image(payload: bytes) -> bool:
    """Whether ``payload`` starts with a recognised image signature."""
    if len(payload) < 12:
        return False
    for magic, kind in _IMAGE_MAGIC_NUMBERS:
        if payload.startswith(magic):
            # RIFF is also used by WAV/AVI; require the WEBP subtype.
            if kind == "webp":
                return payload[8:12] == b"WEBP"
            return True
    return False


# --------------------------------------------------------------------------- #
# Suspicious-request heuristics
# --------------------------------------------------------------------------- #
_SUSPICIOUS_PATTERNS: tuple[str, ...] = (
    "../",
    "..%2f",
    "..%5c",
    "<script",
    "javascript:",
    "onerror=",
    "union select",
    "drop table",
    "etc/passwd",
    "windows/system32",
    "cmd.exe",
    "/bin/sh",
)

_SUSPICIOUS_USER_AGENTS: tuple[str, ...] = (
    "sqlmap",
    "nikto",
    "masscan",
    "nessus",
    "openvas",
    "w3af",
    "skipfish",
)


def is_suspicious_request(path: str, query: str, user_agent: str) -> bool:
    """Cheap heuristic filter for obvious scanner traffic.

    This is defence in depth, not a WAF: it catches noisy automated probes so
    they never reach handler code. Real protection comes from validation,
    parameterised queries and the upload checks above.
    """
    haystack = f"{path} {query}".lower()
    if any(pattern in haystack for pattern in _SUSPICIOUS_PATTERNS):
        return True
    agent = user_agent.lower()
    return any(bot in agent for bot in _SUSPICIOUS_USER_AGENTS)


def log_security_event(
    event_type: str,
    client_ip: str,
    details: dict[str, Any] | None = None,
    severity: str = "INFO",
) -> None:
    """Emit a structured security event for downstream monitoring."""
    payload = {
        "security_event": event_type,
        "client_ip": client_ip,
        "details": details or {},
    }
    message = f"Security event: {event_type} from {client_ip}"
    if severity == "WARNING":
        logger.warning(message, extra=payload)
    elif severity == "ERROR":
        logger.error(message, extra=payload)
    else:
        logger.info(message, extra=payload)
