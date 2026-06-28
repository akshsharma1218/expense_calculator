from django.db import transaction as db_transaction

from ..models import Account
from .base import BaseService, ServiceError


EDITABLE_FIELDS = frozenset({
    "name",
    "account_type",
})


class AccountService(BaseService):

    @staticmethod
    @db_transaction.atomic
    def create_account(
        *,
        user,
        name,
        account_type,
        opening_balance,
    ):

        if opening_balance < 0:
            raise ServiceError(
                "Opening balance cannot be negative."
            )

        return Account.objects.create(
            user=user,
            name=name,
            account_type=account_type,
            opening_balance=opening_balance,
            current_balance=opening_balance,
        )

    @staticmethod
    @db_transaction.atomic
    def update_account(
        *,
        account,
        **data,
    ):

        invalid = set(data) - EDITABLE_FIELDS

        if invalid:
            raise ServiceError(
                f"Immutable fields: {', '.join(sorted(invalid))}"
            )

        for field, value in data.items():
            setattr(
                account,
                field,
                value,
            )

        if data:
            account.save(
                update_fields=list(data.keys())
            )

        return account

    @staticmethod
    @db_transaction.atomic
    def archive_account(account):

        if not account.is_active:
            raise ServiceError(
                "Account already archived."
            )

        account.is_active = False

        account.save(
            update_fields=[
                "is_active",
            ]
        )

        return account

    @staticmethod
    @db_transaction.atomic
    def restore_account(account):

        if account.is_active:
            raise ServiceError(
                "Account already active."
            )

        account.is_active = True

        account.save(
            update_fields=[
                "is_active",
            ]
        )

        return account