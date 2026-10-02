from calendar import month_abbr
from datetime import date
from decimal import Decimal

from django.db.models import Sum, When, Case, F, DecimalField, Q

from ..models import Account, Category, EntryType, GroupBalance, Transaction
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
                is_deleted=False)
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .aggregate(total=Sum("amount"))["total"]
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
            )
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

    @staticmethod
    def monthly_investment(*, user, month, year):
        return (
            Transaction.objects.filter(
                user=user,
                transaction_date__month=month,
                transaction_date__year=year,
                is_deleted=False,
            )
            .filter(account__account_type=Account.AccountType.INVESTMENT)
            .aggregate(total=Sum(
                        Case(
                            When(entry_type=EntryType.CREDIT, then=F("amount")),
                            default=-F("amount"),
                            output_field=DecimalField(),
                        )
                    ))["total"]
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
            investment = DashboardService.monthly_investment(
                user=user, month=month, year=year
            )
            trend.append(
                {
                    "month": month,
                    "year": year,
                    "label": f"{month_abbr[month]} {year}",
                    "income": float(income),
                    "expense": float(expense),
                    "investment": float(investment),
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
            "is_deleted": False,
        }
        if month and year:
            filters["transaction_date__month"] = month
            filters["transaction_date__year"] = year

        rows = (
            Transaction.objects.filter(**filters)
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .values("category__name", "category__category_type")
            .annotate(
                total=Sum(
                        Case(
                            When(entry_type=EntryType.CREDIT, then=-F("amount")),
                            default=F("amount"),
                            output_field=DecimalField(),
                        )
                    )
                )
            .order_by("-total")
        )
        return [
            {
                "name": row["category__name"] or "Uncategorized",
                "type": row["category__category_type"],
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
        accounts = (
            Account.objects.filter(user=user, is_active=True)
            .exclude(account_type=Account.AccountType.INVESTMENT)
            .only("name", "current_balance", "account_type")
            .order_by("current_balance")
        )
        return [
            {
                "name": account.name,
                "balance": float(account.current_balance),
                "type": account.account_type,
            }
            for account in accounts
        ]

    @staticmethod
    def owed_amount(*, user):
        owed = (
            GroupBalance.objects.filter(
                from_user=user
            ).aggregate(total=Sum("balance_amount"))["total"] or Decimal("0.00")
        )
        return owed

    @staticmethod
    def lent_amount(*, user):
        lent = (
            GroupBalance.objects.filter(
                to_user=user
            ).aggregate(total=Sum("balance_amount"))["total"] or Decimal("0.00")
        )
        return lent

    @staticmethod
    def item_breakdown(*, user, month=None, year=None):
        filters = {"user": user, "is_deleted": False}
        if month and year:
            filters["transaction_date__month"] = month
            filters["transaction_date__year"] = year
        rows = (
            Transaction.objects.filter(**filters)
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .values("category__name")
            .annotate(total=Sum(Case(When(entry_type=EntryType.CREDIT, then=-F("amount")), default=F("amount"), output_field=DecimalField())))
            .order_by("-total")
        )
        return [{"name": row["category__name"] or "Uncategorized", "total": float(row["total"] or 0), "type": "expense"} for row in rows]

    @staticmethod
    def timeline_breakdown(*, user, months=6):
        today = __import__("datetime").date.today()
        points = []
        for offset in range(months - 1, -1, -1):
            year, month = DashboardService._shift_month(today.year, today.month, -offset)
            expense = DashboardService.monthly_expense(user=user, month=month, year=year)
            incomes = DashboardService.monthly_income(user=user, month=month, year=year)
            points.append({"label": f"{__import__('calendar').month_abbr[month]} {year}", "expense": float(expense), "income": float(incomes)})
        return points
