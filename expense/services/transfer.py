from django.db import transaction as db_transaction

from ..models import Category, EntryType, Transaction, TransactionGroup, TransactionItem
from .base import BaseService, ServiceError
from .ledger import LedgerService
from .transactions import TransactionService


class TransferService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def create_transfer(
        *,
        user,
        from_account,
        to_account,
        amount,
        category,
        transaction_date,
        merchant=None,
        description="",
        reference_number="",
        tags=None,
        items=None,
    ):
        amount = TransferService._to_decimal(amount)
        if amount <= 0:
            raise ServiceError("Amount must be greater than zero.")
        if not category:
            raise ServiceError("Category is required.")
        if from_account == to_account:
            raise ServiceError("Cannot transfer to the same account.")

        TransactionService.validate_user_resources(
            user=user,
            account=from_account,
            category=category,
            merchant=merchant,
            tags=tags,
        )
        if to_account.user_id != user.id:
            raise ServiceError("Destination account must belong to current user.")

        group = TransactionGroup.objects.create(
            operation_type=TransactionGroup.OperationType.TRANSFER,
            created_by=user,
        )

        shared = {
            "user": user,
            "transaction_group": group,
            "category": category,
            "merchant": merchant,
            "amount": amount,
            "transaction_date": transaction_date,
            "description": description,
            "reference_number": reference_number,
        }

        debit_txn = Transaction.objects.create(
            account=from_account,
            entry_type=EntryType.DEBIT,
            **shared,
        )
        credit_txn = Transaction.objects.create(
            account=to_account,
            entry_type=EntryType.CREDIT,
            **shared,
        )

        if tags:
            debit_txn.tags.set(tags)
            credit_txn.tags.set(tags)

        if items:
            TransactionItem.objects.bulk_create(
                [TransactionItem(transaction=debit_txn, **item) for item in items]
            )

        LedgerService.post_for_transaction(debit_txn)
        LedgerService.post_for_transaction(credit_txn)

        return group
