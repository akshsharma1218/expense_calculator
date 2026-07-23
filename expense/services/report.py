from django.db.models import Sum
from django.db.models.functions import TruncMonth

from ..models import (
    Account,
    Category,
    EntryType,
    Transaction,
)
from .base import BaseService


class ReportService(BaseService):

    @staticmethod
    def monthly_expense(
        *,
        user,
        month,
        year,
    ):
        return (
            Transaction.objects
            .filter(
                user=user,
                entry_type=EntryType.DEBIT,
                transaction_date__month=month,
                transaction_date__year=year,
                is_deleted=False,
            )
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @staticmethod
    def monthly_income(
        *,
        user,
        month,
        year,
    ):
        return (
            Transaction.objects
            .filter(
                user=user,
                entry_type=EntryType.CREDIT,
                transaction_date__month=month,
                transaction_date__year=year,
                is_deleted=False,
            )
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
            .aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    @staticmethod
    def category_summary(
        *,
        user,
        month=None,
        year=None,
    ):

        queryset = (
            Transaction.objects
            .filter(
                user=user,
                entry_type=EntryType.DEBIT,
                is_deleted=False,
            )
            .exclude(category__category_type=Category.CategoryType.TRANSFER)
        )

        if month:
            queryset = queryset.filter(
                transaction_date__month=month,
            )

        if year:
            queryset = queryset.filter(
                transaction_date__year=year,
            )

        return (
            queryset
            .values(
                "category__id",
                "category__name",
            )
            .annotate(
                total=Sum("amount"),
            )
            .order_by("-total")
        )

    @staticmethod
    def account_summary(user):

        return (
            Account.objects
            .filter(
                user=user,
                is_active=True,
            )
            .values(
                "id",
                "name",
                "current_balance",
                "account_type",
            )
            .order_by("name")
        )

