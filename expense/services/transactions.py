from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import F

from ..models import (
    Account,
    Category,
    Merchant,
    Tag,
    Transaction,
    TransactionItem,
)
from .balance import BalanceService
from .base import BaseService, ServiceError
from .ledger import LedgerService


EDITABLE_FIELDS = frozenset({
    "amount",
    "category",
    "merchant",
    "description",
    "transaction_date",
})


class TransactionService(BaseService):

    @staticmethod
    def _lock_account(account_id):
        return (
            Account.objects
            .select_for_update()
            .get(pk=account_id)
        )
    
    @staticmethod
    def validate_amount(amount, items):
        amount = Decimal(amount)

        if amount <= 0:
            raise ServiceError(
                "Amount must be greater than zero."
            )
        
        if items:
            calculated_amount = sum(
                (item["total_price"] for item in items),
                Decimal("0.00"),
            )

            if calculated_amount != amount:
                raise ServiceError(
                    "Transaction amount does not match transaction items."
                )

        return amount

    @staticmethod
    def validate_resources(
        *,
        user,
        account,
        category,
        merchant=None,
        tags=None,
    ):

        if account.user_id != user.id:
            raise ServiceError(
                "Invalid account."
            )

        if (
            not category.is_system
            and category.created_by_id != user.id
        ):
            raise ServiceError(
                "Invalid category."
            )

        if merchant:
            if (
                not merchant.is_system
                and merchant.created_by_id != user.id
            ):
                raise ServiceError(
                    "Invalid merchant."
                )

        if tags:
            for tag in tags:
                if tag.user_id != user.id:
                    raise ServiceError(
                        "Invalid tag."
                    )

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
        tags=None,
        items=None,
        is_group_expense=False,
    ):

        account = TransactionService._lock_account(
                account.pk
            )

        TransactionService.validate_resources(
            user=user,
            account=account,
            category=category,
            merchant=merchant,
            tags=tags,
        )
        amount = TransactionService.validate_amount(
            amount, items
        )
        txn = Transaction.objects.create(
            user=user,
            account=account,
            category=category,
            merchant=merchant,
            amount=amount,
            entry_type=category.normal_side,
            transaction_date=transaction_date,
            description=description,
            is_group_expense=is_group_expense,
        )

        if tags:
            txn.tags.set(tags)

        if items:
            TransactionItem.objects.bulk_create(
                [
                    TransactionItem(
                        transaction=txn,
                        **item,
                    )
                    for item in items
                ]
            )

        BalanceService.apply(
            account=account,
            entry_type=txn.entry_type,
            amount=txn.amount,
        )

        LedgerService.record(
            transaction=txn,
        )

        return txn
    
    @staticmethod
    @db_transaction.atomic
    def update_transaction(
        *,
        transaction_obj,
        items=None,
        tags=None,
        **data,
    ):

        if transaction_obj.is_deleted:
            raise ServiceError(
                "Cannot update deleted transaction."
            )

        invalid = set(data) - EDITABLE_FIELDS

        if invalid:
            raise ServiceError(
                f"Immutable fields: {', '.join(sorted(invalid))}"
            )

        account = TransactionService._lock_account(
                transaction_obj.account_id
            )

        TransactionService.validate_resources(
            user=transaction_obj.user,
            account=account,
            category=data.get(
                "category",
                transaction_obj.category,
            ),
            merchant=data.get(
                "merchant",
                transaction_obj.merchant,
            ),
            tags=tags if tags is not None else transaction_obj.tags.all(),
        )
        


        if not items:
            raise ServiceError(
                "At least one item required."
            )

        if "amount" in data:
            data["amount"] = TransactionService.validate_amount(
                data["amount"], items
            )

        BalanceService.reverse(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

        LedgerService.append_reversal(
            transaction_obj
        )

        for field, value in data.items():
            setattr(
                transaction_obj,
                field,
                value,
            )
        
        transaction_obj.save(
            update_fields=list(data.keys())
        )

        if tags is not None:
            transaction_obj.tags.set(tags)

        if items is not None:

            transaction_obj.items.all().delete()

            TransactionItem.objects.bulk_create(
                [
                    TransactionItem(
                        transaction=transaction_obj,
                        **item,
                    )
                    for item in items
                ]
            )

        BalanceService.apply(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

        account.refresh_from_db(
            fields=[
                "current_balance",
            ]
        )

        LedgerService.record(
            transaction_obj
        )

        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def delete_transaction(transaction_obj):

        if transaction_obj.is_deleted:
            raise ServiceError(
                "Transaction already deleted."
            )

        account = TransactionService._lock_account(
            transaction_obj.account_id
        )

        BalanceService.reverse(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

        LedgerService.append_reversal(
            transaction_obj
        )

        transaction_obj.is_deleted = True
        transaction_obj.save(
            update_fields=["is_deleted"]
        )

        return transaction_obj