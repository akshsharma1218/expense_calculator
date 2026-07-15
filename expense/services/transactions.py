from decimal import Decimal

from django.db import transaction as db_transaction

from ..models import Account, Transaction, TransactionItem
from .balance import BalanceService
from .base import BaseService, ServiceError
from .ledger import LedgerService


EDITABLE_FIELDS = frozenset({
    "amount",
    "category",
    "merchant",
    "description",
    "transaction_date",
    "account",
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
    def _set_items(transaction_obj, items):
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

    @staticmethod
    def _apply_and_record(transaction_obj, account):
        BalanceService.apply(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

        account.refresh_from_db(fields=["current_balance"])
        LedgerService.record(transaction_obj)

    @staticmethod
    def validate_amount(amount, items=None):
        amount = Decimal(amount)

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
        items=None,
    ):

        if account.user_id != user.id:
            raise ServiceError("Invalid account.")

        if not category.is_system and category.created_by_id != user.id:
            raise ServiceError("Invalid category.")

        if merchant and not merchant.is_system and merchant.created_by_id != user.id:
            raise ServiceError("Invalid merchant.")

        if tags:
            for tag in tags:
                if tag.user_id != user.id:
                    raise ServiceError("Invalid tag.")

        if items:
            for item in items:
                if item["total_price"] != item["quantity"] * item["unit_price"]:
                    raise ServiceError("Invalid item total price.")

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
        TransactionService._log_info(
            "Transaction create started",
            user_id=getattr(user, "id", None),
            account_id=getattr(account, "id", None),
            category_id=getattr(category, "id", None),
        )

        account = TransactionService._lock_account(account.pk)

        TransactionService.validate_resources(
            user=user,
            account=account,
            category=category,
            merchant=merchant,
            tags=tags,
            items=items,
        )

        amount = TransactionService.validate_amount(amount, items)

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

        if tags is not None:
            txn.tags.set(tags)

        if items:
            TransactionService._set_items(txn, items)

        TransactionService._apply_and_record(txn, account)

        TransactionService._log_info(
            "Transaction created",
            transaction_id=getattr(txn, "id", None),
            user_id=getattr(user, "id", None),
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
        TransactionService._log_info(
            "Transaction update started",
            transaction_id=getattr(transaction_obj, "id", None),
            user_id=getattr(getattr(transaction_obj, "user", None), "id", None),
        )

        if transaction_obj.is_deleted:
            raise ServiceError("Cannot update deleted transaction.")

        invalid = set(data) - EDITABLE_FIELDS
        if invalid:
            raise ServiceError(
                f"Cannot update immutable fields: {', '.join(sorted(invalid))}"
            )

        account = TransactionService._lock_account(transaction_obj.account_id)

        category = data.get("category", transaction_obj.category)
        merchant = data.get("merchant", transaction_obj.merchant)

        if category.normal_side != transaction_obj.entry_type:
            raise ServiceError("Cannot change transaction type.")

        TransactionService.validate_resources(
            user=transaction_obj.user,
            account=account,
            category=category,
            merchant=merchant,
            tags=tags if tags is not None else transaction_obj.tags.all(),
            items=items,
        )

        if items is not None:
            if not items:
                raise ServiceError("At least one transaction item is required.")

            if "amount" in data:
                data["amount"] = TransactionService.validate_amount(data["amount"], items)
            else:
                data["amount"] = sum(
                    (item["total_price"] for item in items),
                    Decimal("0.00"),
                )
        else:
            data["amount"] = TransactionService.validate_amount(
                data.get("amount", transaction_obj.amount)
            )

        original_entry = LedgerService.latest_posted_entry(transaction_obj)

        TransactionService._log_debug(
            "Transaction reverse phase started",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            original_entry_id=getattr(original_entry, "id", None),
            original_entry_type=original_entry.entry_type,
            original_amount=original_entry.amount,
            account_balance_before_reverse=account.current_balance,
        )

        BalanceService.reverse(
            account=account,
            entry_type=original_entry.entry_type,
            amount=original_entry.amount,
        )

        account.refresh_from_db(fields=["current_balance"])

        TransactionService._log_debug(
            "Transaction reverse balance applied",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            account_balance_after_reverse=account.current_balance,
        )

        reversal_entry = LedgerService.append_reversal(
            transaction_obj,
            original_entry=original_entry,
        )

        TransactionService._log_debug(
            "Transaction reversal ledger entry recorded",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            reversal_entry_id=getattr(reversal_entry, "id", None),
            reversal_entry_type=reversal_entry.entry_type,
            reversal_amount=reversal_entry.amount,
            reversal_posting_number=reversal_entry.posting_number,
            reversal_running_balance=reversal_entry.running_balance,
        )

        for field, value in data.items():
            setattr(transaction_obj, field, value)

        if data:
            transaction_obj.save(update_fields=list(data.keys()))

        if tags is not None:
            transaction_obj.tags.set(tags)

        if items is not None:
            TransactionService._set_items(transaction_obj, items)

        TransactionService._apply_and_record(transaction_obj, account)

        TransactionService._log_info(
            "Transaction updated",
            transaction_id=getattr(transaction_obj, "id", None),
            user_id=getattr(getattr(transaction_obj, "user", None), "id", None),
        )

        return transaction_obj

    @staticmethod
    @db_transaction.atomic
    def delete_transaction(transaction_obj):
        TransactionService._log_info(
            "Transaction delete started",
            transaction_id=getattr(transaction_obj, "id", None),
            user_id=getattr(getattr(transaction_obj, "user", None), "id", None),
        )

        if transaction_obj.is_deleted:
            raise ServiceError("Transaction already deleted.")

        account = TransactionService._lock_account(transaction_obj.account_id)
        original_entry = LedgerService.latest_posted_entry(transaction_obj)

        TransactionService._log_debug(
            "Transaction delete reverse phase started",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            original_entry_id=getattr(original_entry, "id", None),
            original_entry_type=original_entry.entry_type,
            original_amount=original_entry.amount,
            account_balance_before_reverse=account.current_balance,
        )

        BalanceService.reverse(
            account=account,
            entry_type=original_entry.entry_type,
            amount=original_entry.amount,
        )

        account.refresh_from_db(fields=["current_balance"])

        TransactionService._log_debug(
            "Transaction delete reverse balance applied",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            account_balance_after_reverse=account.current_balance,
        )

        reversal_entry = LedgerService.append_reversal(
            transaction_obj,
            original_entry=original_entry,
        )

        TransactionService._log_debug(
            "Transaction delete reversal ledger entry recorded",
            transaction_id=getattr(transaction_obj, "id", None),
            account_id=getattr(account, "id", None),
            reversal_entry_id=getattr(reversal_entry, "id", None),
            reversal_entry_type=reversal_entry.entry_type,
            reversal_amount=reversal_entry.amount,
            reversal_posting_number=reversal_entry.posting_number,
            reversal_running_balance=reversal_entry.running_balance,
        )

        transaction_obj.is_deleted = True
        transaction_obj.save(update_fields=["is_deleted"])

        TransactionService._log_info(
            "Transaction deleted",
            transaction_id=getattr(transaction_obj, "id", None),
            user_id=getattr(getattr(transaction_obj, "user", None), "id", None),
        )

        return transaction_obj
