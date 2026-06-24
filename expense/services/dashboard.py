from decimal import Decimal

from django.db.models import Sum

from ..models import Account, Transaction
from .base import BaseService


class DashboardService(BaseService):
    @staticmethod
    def total_balance(user):
        return Account.objects.filter(user=user, is_active=True).aggregate(total=Sum("current_balance"))["total"] or Decimal("0.00")

    @staticmethod
    def monthly_expense(*, user, month, year):
        return (
            Transaction.objects.filter(
                user=user,
                transaction_type=Transaction.TransactionType.EXPENSE,
                transaction_date__month=month,
                transaction_date__year=year,
                is_deleted=False,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

    @staticmethod
    def monthly_income(*, user, month, year):
        return (
            Transaction.objects.filter(
                user=user,
                transaction_type=Transaction.TransactionType.INCOME,
                transaction_date__month=month,
                transaction_date__year=year,
                is_deleted=False,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

    @staticmethod
    def recent_transactions(*, user, limit=10):
        return (
            Transaction.objects.select_related("account", "category", "merchant")
            .filter(user=user, is_deleted=False)
            .only(
                "id",
                "amount",
                "transaction_date",
                "transaction_type",
                "account_id",
                "category_id",
                "merchant_id",
                "description",
            )
            .order_by("-transaction_date", "-created_at")[:limit]
        )
