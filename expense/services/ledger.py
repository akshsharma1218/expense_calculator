from ..models import EntryType, LedgerEntry
from .balance import BalanceService
from .base import BaseService, ServiceError


class LedgerService(BaseService):
    @staticmethod
    def post(
        *,
        transaction,
        account,
        entry_type,
        amount,
        is_reversal=False,
        reversal_of=None,
    ):
        amount = LedgerService._to_decimal(amount)
        if amount <= 0:
            raise ServiceError("Amount must be greater than zero.")

        account = BalanceService.apply_entry(
            account=account,
            entry_type=entry_type,
            amount=amount,
        )

        return LedgerEntry.objects.create(
            transaction=transaction,
            account=account,
            entry_type=entry_type,
            amount=amount,
            running_balance=account.current_balance,
            is_reversal=is_reversal,
            reversal_of=reversal_of,
        )

    @staticmethod
    def post_for_transaction(transaction):
        return LedgerService.post(
            transaction=transaction,
            account=transaction.account,
            entry_type=transaction.entry_type,
            amount=transaction.amount,
        )

    @staticmethod
    def reverse(*, transaction):
        reversed_ids = LedgerEntry.objects.filter(
            reversal_of__isnull=False,
        ).values_list("reversal_of_id", flat=True)

        active_entries = LedgerEntry.objects.filter(
            transaction=transaction,
            is_reversal=False,
        ).exclude(id__in=reversed_ids).select_related("account")

        reversals = []
        for entry in active_entries:
            opposite = (
                EntryType.CREDIT
                if entry.entry_type == EntryType.DEBIT
                else EntryType.DEBIT
            )
            reversals.append(
                LedgerService.post(
                    transaction=transaction,
                    account=entry.account,
                    entry_type=opposite,
                    amount=entry.amount,
                    is_reversal=True,
                    reversal_of=entry,
                )
            )
        return reversals
