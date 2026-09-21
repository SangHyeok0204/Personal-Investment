"""Exception types for the Kiwoom REST integration."""


class KiwoomError(Exception):
    """Base class for all Kiwoom integration errors."""


class KiwoomConfigError(KiwoomError):
    """Raised when required credentials/settings are missing or blank."""


class KiwoomAuthError(KiwoomError):
    """Raised when the access-token request fails."""


class KiwoomApiError(KiwoomError):
    """Raised when a TR response carries a non-zero return_code."""

    def __init__(self, return_code, return_msg):
        self.return_code = return_code
        self.return_msg = return_msg
        message = return_msg or "Kiwoom API error"
        super().__init__(f"{message} (return_code={return_code})")


class KiwoomRateLimitError(KiwoomApiError):
    """Raised when rate-limit retries are exhausted (HTTP 429 or return_code=5)."""


class KiwoomResponseShapeError(KiwoomError):
    """Raised when a response cannot be parsed into the expected schema."""


class NotSupportedError(KiwoomError):
    """Raised for endpoints that are not supported this round (US equities)."""
