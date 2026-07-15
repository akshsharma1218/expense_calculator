"""
Custom middleware for security headers and error handling.
"""
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from expense.validators import get_client_ip

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add additional security headers to response.
    """

    def process_response(self, request, response):
        """Add security headers."""
        
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS filter
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Clickjacking protection
        response['X-Frame-Options'] = 'DENY'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Feature policy (Permissions-Policy)
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response


class ErrorHandlingMiddleware(MiddlewareMixin):
    """
    Global error handling and logging middleware.
    """

    def process_exception(self, request, exception):
        """Handle exceptions with proper logging."""
        
        client_ip = get_client_ip(request)
        user = request.user.username if request.user.is_authenticated else 'Anonymous'
        
        # Log the error
        logger.error(
            "Unhandled exception captured by middleware",
            extra={
                "exception_type": type(exception).__name__,
                "username": user,
                "client_ip": client_ip,
                "path": request.path,
                "method": request.method,
                "detail": str(exception),
            },
            exc_info=True
        )
        
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if is_ajax:
            return JsonResponse({
                'success': False,
                'detail': 'An error occurred while processing your request. Please try again.',
            }, status=500)
        
        # Let Django's default error handling take over for non-AJAX requests
        return None

