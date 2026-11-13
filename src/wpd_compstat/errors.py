"""Application errors whose messages are safe to show to a user."""


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
