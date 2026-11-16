"""Application errors whose messages are safe to show to a user."""

import traceback
from pathlib import Path


def sanitized_traceback(exc: BaseException) -> str:
    """Exception type and code locations only. The message is left out because it can carry record values."""
    frames = traceback.extract_tb(exc.__traceback__)
    where = " <- ".join(f"{Path(frame.filename).name}:{frame.lineno} {frame.name}" for frame in reversed(frames))
    return f"{type(exc).__name__} at {where or 'unknown location'}"


class AppError(Exception):
    """Expected failure with a message that contains no incident narrative or secrets."""


class AuthError(AppError):
    pass


class CryptoError(AppError):
    pass


class AccessDenied(AppError):
    pass


class ValidationError(AppError):
    pass
