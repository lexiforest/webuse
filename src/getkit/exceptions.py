class GetKitError(Exception):
    """Base exception for the package."""

class SmartSelectorError(GetKitError):
    """Raised when a smart selector cannot be resolved confidently."""
