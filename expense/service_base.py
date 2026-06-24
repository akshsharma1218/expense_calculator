from decimal import Decimal


class ServiceError(ValueError):
    """Raised when a business rule is violated in a service layer operation."""


class BaseService:
    """Shared helpers for service-layer classes."""

    @staticmethod
    def _to_decimal(value, default="0.00"):
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
