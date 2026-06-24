from decimal import Decimal

from django.db.models import Sum

from .models import Budget, Transaction
from .service_base import BaseService


class BudgetService(BaseService):
    @staticmethod
    def get_budget_status(budget_obj):
        spent = (
            Transaction.objects.filter(
                user=budget_obj.user,
                category=budget_obj.category,
                transaction_type=Transaction.TransactionType.EXPENSE,
                transaction_date__month=budget_obj.month,
                transaction_date__year=budget_obj.year,
                is_deleted=False,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        budget_amount = budget_obj.amount or Decimal("0.00")
        remaining = budget_amount - spent
        percentage_used = (
            (spent / budget_amount * Decimal("100")) if budget_amount > 0 else Decimal("0.00")
        )

        return {
            "budget_amount": budget_amount,
            "spent": spent,
            "remaining": remaining,
            "percentage_used": float(percentage_used),
            "is_over_budget": spent > budget_amount,
        }
