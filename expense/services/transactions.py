from decimal import Decimal

from django.db import transaction as db_transaction

from ..models import Category, EntryType, Transaction, TransactionGroup, TransactionItem
from .base import BaseService, ServiceError
from .ledger import LedgerService


EDITABLE_FIELDS = frozenset({
    "amount",
    "category",
    "merchant",
    "description",
    "transaction_date",
    "reference_number",
})


class TransactionService(BaseService):
    @staticmethod
    def operation_type_for_category(category):
        mapping = {
            Category.CategoryType.INCOME: TransactionGroup.OperationType.INCOME,
            Category.CategoryType.EXPENSE: TransactionGroup.OperationType.EXPENSE,
            Category.CategoryType.REFUND: TransactionGroup.OperationType.REFUND,
        }
        return mapping[category.category_type]

    @staticmethod
    def validate_user_resources(*, user, account, category, merchant=None, tags=None):
        if account.user_id != user.id:
            raise ServiceError("Account must belong to current user.")
        if not category:
            raise ServiceError("Category is required.")
        if not category.is_system and category.created_by_id != user.id:
            raise ServiceError("Category must belong to current user.")
        if merchant and not merchant.is_system and merchant.created_by_id != user.id:
            raise ServiceError("Merchant must belong to current user.")
        if tags:
            for tag in tags:
                if tag.user_id != user.id:
                    raise ServiceError("Tags must belong to current user.")

    @staticmethod
    def validate_amount(amount):
        amount = TransactionService._to_decimal(amount)
        if amount <= 0:
            raise ServiceError("Amount must be greater than zero.")
        return amount

    @staticmethod
    @db_transaction.atomic
    def create_transaction(
        *,
        user,
        account,
        category,
        amount,
        transaction_date,
        merchant=None,
        description="",
        reference_number="",
        tags=None,
        items=None,
        is_group_expense=False,
        operation_type=None,
    ):
        amount = TransactionService.validate_amount(amount)
        TransactionService.validate_user_resources(
            user=user,
            account=account,
            category=category,
            merchant=merchant,
            tags=tags,
        )

        entry_type = category.normal_side
        if operation_type is None:
            operation_type = TransactionService.operation_type_for_category(category)

        group = TransactionGroup.objects.create(
            operation_type=operation_type,
            created_by=user,
        )

        txn = Transaction.objects.create(
            user=user,
            transaction_group=group,
            account=account,
            category=category,
            merchant=merchant,
            amount=amount,
            entry_type=entry_type,
            transaction_date=transaction_date,
            description=description,
            reference_number=reference_number,
            is_group_expense=is_group_expense,
        )

        if tags:
            txn.tags.set(tags)

        if items:
            TransactionItem.objects.bulk_create(
                [TransactionItem(transaction=txn, **item) for item in items]
            )

        LedgerService.post_for_transaction(txn)
        return txn

    @staticmethod
    @db_transaction.atomic
    def update_transaction(*, transaction_obj, items=None, tags=None, **data):
        if transaction_obj.is_deleted:
            raise ServiceError("Cannot update deleted transaction.")

        disallowed = set(data.keys()) - EDITABLE_FIELDS
        if disallowed:
            raise ServiceError(
                f"Cannot update immutable fields: {', '.join(sorted(disallowed))}"
            )

        if items is not None:
            if not items:
                raise ServiceError("At least one transaction item is required.")
            data["amount"] = sum(
                (item["total_price"] for item in items),
                Decimal("0.00"),
            )

        if "amount" in data:
            data["amount"] = TransactionService.validate_amount(data["amount"])

        if "category" in data:
            category = data["category"]
            TransactionService.validate_user_resources(
                user=transaction_obj.user,
                account=transaction_obj.account,
                category=category,
            )
            if category.normal_side != transaction_obj.entry_type:
                raise ServiceError(
                    "New category must have the same entry side as the transaction."
                )

        if "merchant" in data and data["merchant"]:
            merchant = data["merchant"]
            if not merchant.is_system and merchant.created_by_id != transaction_obj.user_id:
                raise ServiceError("Merchant must belong to current user.")

        ledger_fields = {"amount", "category"}
        needs_ledger_refresh = bool(ledger_fields & set(data.keys())) or items is not None

        if needs_ledger_refresh:
            LedgerService.reverse(transaction=transaction_obj)

        for field, value in data.items():
            setattr(transaction_obj, field, value)
        transaction_obj.save()

        if tags is not None:
            for tag in tags:
                if tag.user_id != transaction_obj.user_id:
                    raise ServiceError("Tags must belong to current user.")
            transaction_obj.tags.set(tags)

        if items is not None:
            transaction_obj.items.all().delete()
            TransactionItem.objects.bulk_create(
                [TransactionItem(transaction=transaction_obj, **item) for item in items]
            )

        if needs_ledger_refresh:
            LedgerService.post_for_transaction(transaction_obj)

        return transaction_obj

    @staticmethod
    @db_transaction.atomic
    def delete_transaction(transaction_obj):
        if transaction_obj.is_deleted:
            return

        LedgerService.reverse(transaction=transaction_obj)
        transaction_obj.is_deleted = True
        transaction_obj.save(update_fields=["is_deleted"])
