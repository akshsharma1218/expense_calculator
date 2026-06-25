from django.db.models import F

from ..models import Account, EntryType
from .base import BaseService


class BalanceService(BaseService):
    @staticmethod
    def lock_account(account_id):
        return Account.objects.select_for_update().get(pk=account_id)

    @staticmethod
    def credit(*, account, amount):
        amount = BalanceService._to_decimal(amount)
        BalanceService.lock_account(account.pk)
        Account.objects.filter(pk=account.pk).update(
            current_balance=F("current_balance") + amount
        )
        account.refresh_from_db(fields=["current_balance"])
        return account

    @staticmethod
    def debit(*, account, amount):
        amount = BalanceService._to_decimal(amount)
        BalanceService.lock_account(account.pk)
        Account.objects.filter(pk=account.pk).update(
            current_balance=F("current_balance") - amount
        )
        account.refresh_from_db(fields=["current_balance"])
        return account

    @staticmethod
    def apply_entry(*, account, entry_type, amount):
        if entry_type == EntryType.CREDIT:
            return BalanceService.credit(account=account, amount=amount)
        return BalanceService.debit(account=account, amount=amount)
