from django.db import transaction as db_transaction

from ..models import Account, EntryType, LedgerEntry
from .base import BaseService, ServiceError


class LedgerService(BaseService):

    @classmethod
    def _normalize_entry(cls, entry_type, amount):
        normalized_amount = cls._to_decimal(amount)

        if normalized_amount < 0:
            normalized_amount = abs(normalized_amount)
            entry_type = (
                EntryType.CREDIT
                if entry_type == EntryType.DEBIT
                else EntryType.DEBIT
            )

        return entry_type, normalized_amount

    @staticmethod
    def latest_posted_entry(transaction):
        entry = (
            LedgerEntry.objects
            .filter(
                transaction=transaction,
                reversal_of__isnull=True,
            )
            .order_by("-posting_number")
            .select_related("account")
            .first()
        )

        if entry is None:
            raise ServiceError(
                "Original ledger entry not found."
            )

        return entry

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
            )
            .order_by("-posting_number")
            .first()
        )

        return last_entry
        

    @staticmethod
    def _expected_balance(
        *,
        account_type,
        previous_balance,
        entry_type,
        amount,
    ):
        is_credit_card = account_type == Account.AccountType.CREDIT_CARD

        if entry_type == EntryType.CREDIT:
            return (
                previous_balance - amount
                if is_credit_card
                else previous_balance + amount
            )

        if entry_type == EntryType.DEBIT:
            return (
                previous_balance + amount
                if is_credit_card
                else previous_balance - amount
            )

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
            account_type=account.account_type,
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
    
        account = Account.objects.get(pk=transaction.account_id)
        entry_type, amount = LedgerService._normalize_entry(
            transaction.entry_type,
            transaction.amount,
        )

        if (entry_type, amount) != (transaction.entry_type, transaction.amount):
            LedgerService._log_warning(
                "Normalizing negative ledger amount",
                transaction_id=getattr(transaction, "id", None),
                account_id=getattr(account, "id", None),
                original_entry_type=transaction.entry_type,
                normalized_entry_type=entry_type,
                original_amount=transaction.amount,
                normalized_amount=amount,
            )

        last_entry = LedgerService._last(account)
        previous_balance = last_entry.running_balance if last_entry else account.opening_balance

        posting_number = last_entry.posting_number + 1 if last_entry else 1

        running_balance = LedgerService._validate_balance(
            account=account,
            previous_balance=previous_balance,
            entry_type=entry_type,
            amount=amount,
        )

        return LedgerEntry.objects.create(
            transaction=transaction,
            account=account,
            entry_type=entry_type,
            amount=amount,
            running_balance=running_balance,
            posting_number=posting_number,
        )
    
    @staticmethod
    @db_transaction.atomic
    def append_reversal(transaction, *, original_entry=None):
        """
        Append a reversal ledger entry.

        The original ledger entry is never modified.
        """

        original = original_entry or LedgerService.latest_posted_entry(transaction)

        if LedgerEntry.objects.filter(
            reversal_of=original,
        ).exists():
            raise ServiceError(
                "Transaction already reversed."
            )
        
        account = Account.objects.get(pk=original.account_id)
        original_entry_type, original_amount = LedgerService._normalize_entry(
            original.entry_type,
            original.amount,
        )

        if (original_entry_type, original_amount) != (original.entry_type, original.amount):
            LedgerService._log_warning(
                "Normalizing negative reversal ledger amount",
                transaction_id=getattr(transaction, "id", None),
                original_entry_id=getattr(original, "id", None),
                account_id=getattr(account, "id", None),
                original_entry_type=original.entry_type,
                normalized_entry_type=original_entry_type,
                original_amount=original.amount,
                normalized_amount=original_amount,
            )

        last_entry = LedgerService._last(account)
        previous_balance = last_entry.running_balance if last_entry else account.opening_balance

        posting_number = last_entry.posting_number + 1 if last_entry else 1

        reverse_type = (
            EntryType.CREDIT
            if original_entry_type == EntryType.DEBIT
            else EntryType.DEBIT
        )

        running_balance = LedgerService._validate_balance(
            account=account,
            previous_balance=previous_balance,
            entry_type=reverse_type,
            amount=original_amount,
        )

        return LedgerEntry.objects.create(
            transaction=transaction,
            account=account,
            entry_type=reverse_type,
            amount=original_amount,
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
            balance = LedgerService._expected_balance(
                account_type=account.account_type,
                previous_balance=balance,
                entry_type=entry.entry_type,
                amount=entry.amount,
            )
            
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