from django.db import transaction as db_transaction

from ..models import EntryType, LedgerEntry
from .base import BaseService, ServiceError


class LedgerService(BaseService):

    @staticmethod
    def _last(account):
        """
        Returns the latest ledger entry for the account.
        Falls back to None if no ledger exists.
        """

        last_entry = (
            LedgerEntry.objects
            .filter(
                account=account,
                reversal_of__isnull=True,
            )
            .order_by("-posting_number")
            .first()
        )

        return last_entry
        

    @staticmethod
    def _expected_balance(
        *,
        previous_balance,
        entry_type,
        amount,
    ):
        if entry_type == EntryType.CREDIT:
            return previous_balance + amount

        if entry_type == EntryType.DEBIT:
            return previous_balance - amount

        raise ServiceError("Invalid entry type.")

    @staticmethod
    def _validate_balance(
        *,
        account,
        previous_balance,
        entry_type,
        amount,
    ):
        expected = LedgerService._expected_balance(
            previous_balance=previous_balance,
            entry_type=entry_type,
            amount=amount,
        )

        if expected != account.current_balance:
            raise ServiceError(
                f"""
                Ledger balance mismatch.

                Previous Ledger Balance : {previous_balance}
                Transaction Amount      : {amount}
                Entry Type              : {entry_type}
                Expected Balance        : {expected}
                Current Balance         : {account.current_balance}
                """
            )

        return expected

    @staticmethod
    @db_transaction.atomic
    def record(transaction):
        """
        Append immutable ledger entry.

        Assumes:
            - Transaction already exists
            - Account balance has already been updated
            - Account row is locked by caller
        """

        if transaction.is_deleted:
            raise ServiceError(
                "Cannot post deleted transaction."
            )
    
        last_entry = LedgerService._last(transaction.account)
        previous_balance = last_entry.running_balance if last_entry else transaction.account.opening_balance

        posting_number = last_entry.posting_number + 1 if last_entry else 1

        running_balance = LedgerService._validate_balance(
            account=transaction.account,
            previous_balance=previous_balance,
            entry_type=transaction.entry_type,
            amount=transaction.amount,
        )

        return LedgerEntry.objects.create(
            transaction=transaction,
            account=transaction.account,
            entry_type=transaction.entry_type,
            amount=transaction.amount,
            running_balance=running_balance,
            posting_number=posting_number,
        )
    
    @staticmethod
    @db_transaction.atomic
    def append_reversal(transaction):
        """
        Append a reversal ledger entry.

        The original ledger entry is never modified.
        """

        original = (
            LedgerEntry.objects
            .filter(
                transaction=transaction,
                reversal_of__isnull=True,
            )
            .order_by("-posting_number")
            .select_related("account")
            .first()
        )

        if original is None:
            raise ServiceError(
                "Original ledger entry not found."
            )

        if LedgerEntry.objects.filter(
            reversal_of=original,
        ).exists():
            raise ServiceError(
                "Transaction already reversed."
            )
        
        last_entry = LedgerService._last(transaction.account)
        previous_balance = last_entry.running_balance if last_entry else transaction.account.opening_balance

        posting_number = last_entry.posting_number + 1 if last_entry else 1

        reverse_type = (
            EntryType.CREDIT
            if original.entry_type == EntryType.DEBIT
            else EntryType.DEBIT
        )

        running_balance = LedgerService._validate_balance(
            account=original.account,
            previous_balance=previous_balance,
            entry_type=reverse_type,
            amount=original.amount,
        )

        return LedgerEntry.objects.create(
            transaction=transaction,
            account=original.account,
            entry_type=reverse_type,
            amount=original.amount,
            running_balance=running_balance,
            reversal_of=original,
            posting_number=posting_number,
        )


    @staticmethod
    def validate_chain(account):
        """
        Validates the ledger chain.

        Raises ServiceError if any running balance is incorrect.
        """

        balance = account.opening_balance

        entries = (
            LedgerEntry.objects
            .filter(account=account)
            .order_by(
                "posting_number",
            )
        )
        expected_posting = 1
        for entry in entries:

            if entry.entry_type == EntryType.CREDIT:
                balance += entry.amount
            else:
                balance -= entry.amount
            
            if entry.posting_number != expected_posting:
                raise ServiceError(
                    f"Missing posting number {expected_posting}"
                )

            expected_posting += 1

            if balance != entry.running_balance:
                raise ServiceError(
                    f"""
                        Ledger corruption detected.

                        Ledger Entry : {entry.id}

                        Expected Balance : {balance}

                        Ledger Posting Number : {entry.posting_number}

                        Ledger Balance : {entry.running_balance}
                        """
                )

        return True