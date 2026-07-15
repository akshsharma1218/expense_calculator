"""
Security and validation utilities for the expense calculator application.
"""
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.core.exceptions import ValidationError
from django.utils.html import escape

logger = logging.getLogger(__name__)

# File upload security
ALLOWED_UPLOAD_EXTENSIONS = {'csv', 'png', 'jpg', 'jpeg', 'gif', 'pdf'}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


class ValidationError(Exception):
    """Custom validation error for consistent error handling."""
    pass


def validate_file_upload(file, allowed_extensions=None, max_size=MAX_UPLOAD_SIZE):
    """
    Validate uploaded file for security.
    
    Args:
        file: The uploaded file object
        allowed_extensions: Set of allowed file extensions
        max_size: Maximum file size in bytes
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_UPLOAD_EXTENSIONS
    
    # Check file size
    if file.size > max_size:
        return False, f"File exceeds maximum size of {max_size // (1024*1024)}MB"
    
    # Check file extension
    filename = file.name.lower()
    if not any(filename.endswith(f'.{ext}') for ext in allowed_extensions):
        return False, f"File type not allowed. Allowed: {', '.join(allowed_extensions)}"
    
    # Check for suspicious file extensions
    if filename.endswith(('.exe', '.sh', '.bat', '.cmd', '.com', '.pif', '.scr')):
        return False, "Executable file types are not allowed"
    
    return True, None


def validate_decimal(value, field_name="amount"):
    """
    Validate and convert value to Decimal.
    
    Args:
        value: The value to validate
        field_name: Name of the field for error messages
        
    Returns:
        Decimal: The validated decimal value
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        decimal_value = Decimal(str(value))
        
        return decimal_value
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field_name} must be a valid decimal number")


def validate_date(value, date_format="%Y-%m-%d"):
    """
    Validate date string.
    
    Args:
        value: The date string to validate
        date_format: Expected date format
        
    Returns:
        datetime.date: The parsed date
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        return datetime.strptime(str(value), date_format).date()
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid date format. Expected {date_format}")


def validate_csv_headers(headers, required_headers):
    """
    Validate CSV headers against required fields.
    
    Args:
        headers: List of CSV headers
        required_headers: Set of required header names
        
    Returns:
        tuple: (is_valid, missing_headers)
    """
    headers_lower = [h.lower().strip() for h in headers]
    required_lower = [h.lower() for h in required_headers]
    
    missing = [h for h in required_lower if h not in headers_lower]
    
    return len(missing) == 0, missing


def sanitize_input(value, max_length=1000):
    """
    Sanitize user input to prevent XSS.
    
    Args:
        value: The input value to sanitize
        max_length: Maximum allowed length
        
    Returns:
        str: Sanitized value
        
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        return ""
    
    value_str = str(value).strip()
    
    if len(value_str) > max_length:
        raise ValidationError(f"Input exceeds maximum length of {max_length} characters")
    
    # Escape HTML to prevent XSS
    return escape(value_str)


def safe_json_response(data, default_value=None):
    """
    Safely serialize data to JSON with error handling.
    
    Args:
        data: Data to serialize
        default_value: Default value if serialization fails
        
    Returns:
        dict: Serializable dictionary
    """
    import json
    
    try:
        json.dumps(data)
        return data
    except (TypeError, ValueError) as e:
        logger.error(
            "JSON serialization error",
            extra={"error_detail": str(e)},
            exc_info=True,
        )
        return default_value or {}


def log_security_event(event_type, request, details=""):
    """
    Log security-related events.
    
    Args:
        event_type: Type of security event (e.g., 'failed_auth', 'suspicious_upload')
        request: Django request object
        details: Additional details about the event
    """
    logger.error(
        "Security event detected",
        extra={
            "event_type": event_type,
            "username": request.user.username if request.user.is_authenticated else "Anonymous",
            "client_ip": get_client_ip(request),
            "detail": str(details),
            "path": request.path,
        },
    )


def get_client_ip(request):
    """
    Get client IP address from request, accounting for proxies.
    
    Args:
        request: Django request object
        
    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
