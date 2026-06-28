from django.db import transaction as db_transaction

from ..models import (
    Account,
    Category,
    EntryType,
    Transfer,
)
from .base import BaseService, ServiceError
from .transactions import TransactionService


class TransferService(BaseService):

    @staticmethod
    def _get_transfer_categories():

        categories = (
            Category.objects
            .filter(
                category_type=Category.CategoryType.TRANSFER,
                is_system=True,
            )
        )

        debit_category = None
        credit_category = None

        for category in categories:

            if category.normal_side == EntryType.DEBIT:
                debit_category = category

            elif category.normal_side == EntryType.CREDIT:
                credit_category = category

        if debit_category is None or credit_category is None:
            raise ServiceError(
                "System transfer categories are not configured."
            )

        return debit_category, credit_category

    @staticmethod
    def validate_accounts(
        *,
        user,
        from_account,
        to_account,
    ):

        if from_account.pk == to_account.pk:
            raise ServiceError(
                "Source and destination accounts must be different."
            )

        if from_account.user_id != user.id:
            raise ServiceError(
                "Invalid source account."
            )

        if to_account.user_id != user.id:
            raise ServiceError(
                "Invalid destination account."
            )

    @staticmethod
    @db_transaction.atomic
    def create_transfer(
        *,
        user,
        from_account,
        to_account,
        amount,
        transaction_date,
        notes="",
    ):

        TransferService.validate_accounts(
            user=user,
            from_account=from_account,
            to_account=to_account,
        )

        debit_category, credit_category = (
            TransferService._get_transfer_categories()
        )

        debit_transaction = (
            TransactionService.create_transaction(
                user=user,
                account=from_account,
                category=debit_category,
                amount=amount,
                transaction_date=transaction_date,
                description=notes,
            )
        )

        credit_transaction = (
            TransactionService.create_transaction(
                user=user,
                account=to_account,
                category=credit_category,
                amount=amount,
                transaction_date=transaction_date,
                description=notes,
            )
        )
        transfer_type = Transfer.Type.BILL_PAYMENT if to_account.account_type == Account.AccountType.CREDIT_CARD else Transfer.Type.TRANSFER

        return Transfer.objects.create(
            user=user,
            transfer_type=transfer_type,
            debit_transaction=debit_transaction,
            credit_transaction=credit_transaction,
            notes=notes,
            created_by=user,
        )

    @staticmethod
    @db_transaction.atomic
    def update_transfer(
        *,
        transfer,
        from_account,
        to_account,
        amount,
        transaction_date,
        notes="",
    ):

        if transfer.is_deleted:
            raise ServiceError(
                "Cannot update deleted transfer."
            )

        TransferService.validate_accounts(
            user=transfer.user,
            from_account=from_account,
            to_account=to_account,
        )

        debit_category, credit_category = (
            TransferService._get_transfer_categories()
        )

        TransactionService.update_transaction(
            transaction_obj=transfer.debit_transaction,
            account=from_account,
            category=debit_category,
            amount=amount,
            transaction_date=transaction_date,
            description=notes,
        )

        TransactionService.update_transaction(
            transaction_obj=transfer.credit_transaction,
            account=to_account,
            category=credit_category,
            amount=amount,
            transaction_date=transaction_date,
            description=notes,
        )

        
        transfer.notes = notes
        transfer.transfer_type = Transfer.Type.BILL_PAYMENT if to_account.account_type == Account.AccountType.CREDIT_CARD else Transfer.Type.TRANSFER
  
        transfer.save(
            update_fields=[
                "transfer_type",
                "notes",
            ]
        )

        return transfer

    @staticmethod
    @db_transaction.atomic
    def delete_transfer(transfer):

        if transfer.is_deleted:
            raise ServiceError(
                "Transfer already deleted."
            )

        TransactionService.delete_transaction(
            transfer.debit_transaction
        )

        TransactionService.delete_transaction(
            transfer.credit_transaction
        )

        transfer.is_deleted = True

        transfer.save(
            update_fields=[
                "is_deleted",
            ]
        )

        return transfer