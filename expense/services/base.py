from decimal import Decimal
import logging


_RESERVED_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys())


class ServiceError(ValueError):
    """Raised when a business rule is violated in a service layer operation."""


class BaseService:
    """Shared helpers for service-layer classes."""

    @classmethod
    def _logger(cls):
        return logging.getLogger(f"expense.services.{cls.__module__.split('.')[-1]}")

    @classmethod
    def _safe_extra(cls, extra):
        if not extra:
            return None

        sanitized = {}
        for key, value in extra.items():
            safe_key = str(key)
            if safe_key in _RESERVED_LOG_RECORD_KEYS:
                safe_key = f"ctx_{safe_key}"
            sanitized[safe_key] = value
        return sanitized

    @classmethod
    def _log_info(cls, message, **extra):
        cls._logger().info(message, extra=cls._safe_extra(extra))

    @classmethod
    def _log_debug(cls, message, **extra):
        cls._logger().debug(message, extra=cls._safe_extra(extra))

    @classmethod
    def _log_warning(cls, message, **extra):
        cls._logger().warning(message, extra=cls._safe_extra(extra))

    @classmethod
    def _log_error(cls, message, *, exc_info=False, **extra):
        cls._logger().error(
            message,
            extra=cls._safe_extra(extra),
            exc_info=exc_info,
        )

    @staticmethod
    def _to_decimal(value, default="0.00"):
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
