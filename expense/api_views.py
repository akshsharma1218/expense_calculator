"""Compatibility shims for upload views.

Upload handlers now live in expense.views.
"""

from .views import receipt_upload, transactions_upload

__all__ = ["receipt_upload", "transactions_upload"]
