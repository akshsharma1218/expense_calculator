from django.db.models import F

from ..models import Account, EntryType
from .base import BaseService, ServiceError


class BalanceService(BaseService):

    @staticmethod
    def _is_credit_card(account: Account):
        return account.account_type == Account.AccountType.CREDIT_CARD

    @staticmethod
    def validate_account(account: Account):

        if not account.is_active:
            raise ServiceError("Account is inactive.")

    @staticmethod
    def credit(*, account: Account, amount):
        BalanceService.validate_account(account)

        is_credit_card = BalanceService._is_credit_card(account)
        expression = (
            F("current_balance") - amount
            if is_credit_card
            else F("current_balance") + amount
        )

        Account.objects.filter(
            pk=account.pk
        ).update(
            current_balance=expression
        )


    @staticmethod
    def debit(*, account: Account, amount):
        BalanceService.validate_account(account)

        is_credit_card = BalanceService._is_credit_card(account)
        expression = (
            F("current_balance") + amount
            if is_credit_card
            else F("current_balance") - amount
        )

        Account.objects.filter(
            pk=account.pk
        ).update(
            current_balance=expression
        )


    @staticmethod
    def apply(*, account: Account, entry_type: str, amount):
        if entry_type == EntryType.CREDIT:
            BalanceService.credit(
                account=account,
                amount=amount,
            )
        elif entry_type == EntryType.DEBIT:
            BalanceService.debit(
                account=account,
                amount=amount,
            )
        else:
            raise ServiceError("Invalid entry type.")

    @staticmethod
    def reverse(*, account: Account, entry_type: str, amount):
        if entry_type == EntryType.CREDIT:
            BalanceService.debit(
                account=account,
                amount=amount,
            )
        elif entry_type == EntryType.DEBIT:
            BalanceService.credit(
                account=account,
                amount=amount,
            )
        else:
            raise ServiceError("Invalid entry type.")