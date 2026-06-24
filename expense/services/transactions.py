from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import F

from ..models import Account, LedgerEntry, Transaction, TransactionItem
from .base import BaseService, ServiceError


class TransactionService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def create_transaction(
        *,
        user,
        account,
        amount,
        transaction_type,
        transaction_date,
        category=None,
        merchant=None,
        transfer_account=None,
        description="",
        reference_number="",
        tags=None,
        items=None,
        is_group_expense=False,
    ):
        if transaction_type == Transaction.TransactionType.TRANSFER:
            if not transfer_account:
                raise ServiceError("Transfer account is required for transfer transactions.")
            if transfer_account == account:
                raise ServiceError("Cannot transfer to the same account.")
            if category is None:
                raise ServiceError("Category is required for transfer transactions.")

            txn = Transaction.objects.create(
                user=user,
                account=account,
                transfer_account=transfer_account,
                category=category,
                merchant=merchant,
                amount=amount,
                transaction_type=transaction_type,
                transaction_date=transaction_date,
                description=description,
                reference_number=reference_number,
                is_group_expense=is_group_expense,
            )
        else:
            if category is None:
                raise ServiceError("Category is required for non-transfer transactions.")

            txn = Transaction.objects.create(
                user=user,
                account=account,
                category=category,
                merchant=merchant,
                amount=amount,
                transaction_type=transaction_type,
                transaction_date=transaction_date,
                description=description,
                reference_number=reference_number,
                is_group_expense=is_group_expense,
            )

        if tags:
            txn.tags.set(tags)

        if items:
            TransactionItem.objects.bulk_create([TransactionItem(transaction=txn, **item) for item in items])

        TransactionService._apply_balance_change(txn)
        return txn

    @staticmethod
    @db_transaction.atomic
    def create_transfer(*, user, from_account, to_account, amount, transaction_date, category, description="", reference_number=""):
        return TransactionService.create_transaction(
            user=user,
            account=from_account,
            category=category,
            amount=amount,
            transaction_type=Transaction.TransactionType.TRANSFER,
            transaction_date=transaction_date,
            transfer_account=to_account,
            description=description,
            reference_number=reference_number,
        )

    @staticmethod
    @db_transaction.atomic
    def update_transaction(*, transaction_obj, **data):
        if transaction_obj.is_deleted:
            raise ServiceError("Cannot update deleted transaction")

        TransactionService._reverse_balance(transaction_obj)
        for field, value in data.items():
            setattr(transaction_obj, field, value)
        transaction_obj.save()
        TransactionService._apply_balance_change(transaction_obj)
        return transaction_obj

    @staticmethod
    @db_transaction.atomic
    def delete_transaction(transaction_obj):
        if transaction_obj.is_deleted:
            return

        TransactionService._reverse_balance(transaction_obj)
        transaction_obj.is_deleted = True
        transaction_obj.save(update_fields=["is_deleted"])

    @staticmethod
    def _apply_balance_change(transaction_obj):
        account = transaction_obj.account

        if transaction_obj.transaction_type == Transaction.TransactionType.INCOME:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") + transaction_obj.amount)
            account.refresh_from_db()
            LedgerEntry.objects.create(
                transaction=transaction_obj,
                account=account,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount=transaction_obj.amount,
                running_balance=account.current_balance,
            )
        elif transaction_obj.transaction_type == Transaction.TransactionType.EXPENSE:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") - transaction_obj.amount)
            account.refresh_from_db()
            LedgerEntry.objects.create(
                transaction=transaction_obj,
                account=account,
                entry_type=LedgerEntry.EntryType.DEBIT,
                amount=transaction_obj.amount,
                running_balance=account.current_balance,
            )
        elif transaction_obj.transaction_type == Transaction.TransactionType.REFUND:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") + transaction_obj.amount)
            account.refresh_from_db()
            LedgerEntry.objects.create(
                transaction=transaction_obj,
                account=account,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount=transaction_obj.amount,
                running_balance=account.current_balance,
            )
        elif transaction_obj.transaction_type == Transaction.TransactionType.TRANSFER:
            transfer_account = transaction_obj.transfer_account
            if transfer_account:
                Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") - transaction_obj.amount)
                Account.objects.filter(pk=transfer_account.pk).update(current_balance=F("current_balance") + transaction_obj.amount)
                account.refresh_from_db()
                transfer_account.refresh_from_db()
                LedgerEntry.objects.create(
                    transaction=transaction_obj,
                    account=account,
                    entry_type=LedgerEntry.EntryType.DEBIT,
                    amount=transaction_obj.amount,
                    running_balance=account.current_balance,
                )
                LedgerEntry.objects.create(
                    transaction=transaction_obj,
                    account=transfer_account,
                    entry_type=LedgerEntry.EntryType.CREDIT,
                    amount=transaction_obj.amount,
                    running_balance=transfer_account.current_balance,
                )

    @staticmethod
    def _reverse_balance(transaction_obj):
        account = transaction_obj.account

        if transaction_obj.transaction_type == Transaction.TransactionType.INCOME:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") - transaction_obj.amount)
        elif transaction_obj.transaction_type == Transaction.TransactionType.EXPENSE:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") + transaction_obj.amount)
        elif transaction_obj.transaction_type == Transaction.TransactionType.REFUND:
            Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") - transaction_obj.amount)
        elif transaction_obj.transaction_type == Transaction.TransactionType.TRANSFER:
            transfer_account = transaction_obj.transfer_account
            if transfer_account:
                Account.objects.filter(pk=account.pk).update(current_balance=F("current_balance") + transaction_obj.amount)
                Account.objects.filter(pk=transfer_account.pk).update(current_balance=F("current_balance") - transaction_obj.amount)
