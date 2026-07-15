from calendar import month_abbr
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from ..models import Account, EntryType, Transaction
from .base import BaseService


class DashboardService(BaseService):
    @staticmethod
    def total_balance(user):
        DashboardService._log_info(
            "Dashboard total balance requested",
            user_id=getattr(user, "id", None),
        )
        accounts = Account.objects.filter(user=user, is_active=True).only(
            "account_type", "current_balance"
        )
        return sum(
            (
                -account.current_balance
                if account.account_type == Account.AccountType.CREDIT_CARD
                else account.current_balance
            )
            for account in accounts
        ) or Decimal("0.00")

    @staticmethod
    def monthly_expense(*, user, month, year):
        return (
            Transaction.objects.filter(
                user=user,
                entry_type=EntryType.DEBIT,
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
                entry_type=EntryType.CREDIT,
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
                "entry_type",
                "account_id",
                "category_id",
                "merchant_id",
                "description",
            )
            .order_by("-transaction_date", "-created_at")[:limit]
        )

    @staticmethod
    def _shift_month(year, month, delta):
        month += delta
        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1
        return year, month

    @staticmethod
    def monthly_trend(*, user, months=6):
        DashboardService._log_info(
            "Dashboard monthly trend requested",
            user_id=getattr(user, "id", None),
            months=months,
        )
        today = date.today()
        trend = []
        for offset in range(months - 1, -1, -1):
            year, month = DashboardService._shift_month(
                today.year, today.month, -offset
            )
            income = DashboardService.monthly_income(
                user=user, month=month, year=year
            )
            expense = DashboardService.monthly_expense(
                user=user, month=month, year=year
            )
            trend.append(
                {
                    "month": month,
                    "year": year,
                    "label": f"{month_abbr[month]} {year}",
                    "income": float(income),
                    "expense": float(expense),
                    "savings": float(income - expense),
                }
            )
        return trend

    @staticmethod
    def category_breakdown(*, user, month=None, year=None):
        DashboardService._log_info(
            "Dashboard category breakdown requested",
            user_id=getattr(user, "id", None),
            month=month,
            year=year,
        )
        filters = {
            "user": user,
            "entry_type": EntryType.DEBIT,
            "is_deleted": False,
        }
        if month and year:
            filters["transaction_date__month"] = month
            filters["transaction_date__year"] = year

        rows = (
            Transaction.objects.filter(**filters)
            .values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )
        return [
            {
                "name": row["category__name"] or "Uncategorized",
                "total": float(row["total"] or 0),
            }
            for row in rows
        ]

    @staticmethod
    def account_distribution(*, user):
        DashboardService._log_info(
            "Dashboard account distribution requested",
            user_id=getattr(user, "id", None),
        )
        accounts = Account.objects.filter(user=user, is_active=True).only(
            "name", "current_balance", "account_type"
        )
        return [
            {
                "name": account.name,
                "balance": float(account.current_balance),
                "type": account.account_type,
            }
            for account in accounts
        ]
