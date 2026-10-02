from decimal import Decimal

from django.db import transaction as db_transaction
from ..models import Account, EntryType, Transaction, TransactionItem, Category
from .balance import BalanceService
from .base import BaseService, ServiceError
from .groups import GroupService


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
    def normalize_entry_type(entry_type, negative_amount=False):
        if negative_amount:
            return EntryType.DEBIT if entry_type == EntryType.CREDIT else EntryType.CREDIT
        return entry_type

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
    def _apply_balance(transaction_obj, account):
        BalanceService.apply(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

    @staticmethod
    def validate_amount(amount, items=None):
        amount = Decimal(amount)
        TransactionService._log_info(
            "Validating transaction amount",
            amount=amount,
            items=items,
        )
        if items:
            calculated_amount = sum(
                (item["total_price"] for item in items),
                Decimal("0.00"),
            )

            if abs(calculated_amount) != amount:
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
        items=None,
    ):

        if account.user_id != user.id:
            raise ServiceError("Invalid account.")

        if not category.is_system and category.created_by_id != user.id:
            raise ServiceError("Invalid category.")

        if merchant and not merchant.is_system and merchant.created_by_id != user.id:
            raise ServiceError("Invalid merchant.")

        if items:
            for item in items:
                if item["total_price"] != item["quantity"] * item["unit_price"]:
                    raise ServiceError("Invalid item total price.")

    @staticmethod
    def create_default_items_from_transaction(transaction_obj):
        return [
            {
                "name": transaction_obj.description or "Item",
                "quantity": 1,
                "unit_price": transaction_obj.amount,
                "total_price": transaction_obj.amount,
            }
        ]
    
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
            items=items,
        )

        amount = Decimal(amount)
        negative_amount = amount < 0
        amount = TransactionService.validate_amount(abs(amount), items)

        normalized_entry_type = TransactionService.normalize_entry_type(
            category.normal_side,
            negative_amount=negative_amount,
        )
        
        txn = Transaction.objects.create(
            user=user,
            account=account,
            category=category,
            merchant=merchant,
            amount=amount,
            entry_type=normalized_entry_type,
            transaction_date=transaction_date,
            description=description,
            is_group_expense=is_group_expense,
        )

        if not items:
            items = TransactionService.create_default_items_from_transaction(txn)

        if items:
            TransactionService._set_items(txn, items)

        TransactionService._apply_balance(txn, account)

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
        
        original_transaction = Transaction.objects.get(pk=transaction_obj.pk)
        original_account = TransactionService._lock_account(original_transaction.account_id)
        account = TransactionService._lock_account(data.get("account", transaction_obj.account).id)

        TransactionService._log_debug(
            "Transaction update account locked",
            transaction_id=getattr(transaction_obj, "id", None),
            original_account_id=getattr(original_account, "id", None),
            new_account_id=getattr(account, "id", None),
        )

        category = data.get("category", transaction_obj.category)
        merchant = data.get("merchant", transaction_obj.merchant)


        TransactionService.validate_resources(
            user=transaction_obj.user,
            account=account,
            category=category,
            merchant=merchant,
            items=items,
        )

        negative_amount = (
            Decimal(data["amount"]) < 0
            if "amount" in data
            else original_transaction.entry_type != original_transaction.category.normal_side
        )
        if items is None:
            if "amount" in data:
                data["amount"] = TransactionService.validate_amount(abs(Decimal(data["amount"])))
        elif not items:
            raise ServiceError("At least one transaction item is required.")
        else:
            if "amount" in data:
                data["amount"] = TransactionService.validate_amount(abs(Decimal(data["amount"])), items)
            else:
                raise ServiceError("Amount is required when updating transaction items.")

        BalanceService.reverse(
            account=original_account,
            entry_type=original_transaction.entry_type,
            amount=original_transaction.amount,
        )

        for field, value in data.items():
            setattr(transaction_obj, field, value)

        if data:
            if "amount" in data or "category" in data:
                transaction_obj.entry_type = TransactionService.normalize_entry_type(
                    category.normal_side,
                    negative_amount=negative_amount,
                )
                data["entry_type"] = transaction_obj.entry_type
            transaction_obj.save(update_fields=list(data.keys()))

        if items is not None:
            TransactionService._set_items(transaction_obj, items)

        TransactionService._apply_balance(transaction_obj, account)

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
        BalanceService.reverse(
            account=account,
            entry_type=transaction_obj.entry_type,
            amount=transaction_obj.amount,
        )

        transaction_obj.is_deleted = True
        transaction_obj.save(update_fields=["is_deleted"])

        TransactionService._log_info(
            "Transaction deleted",
            transaction_id=getattr(transaction_obj, "id", None),
            user_id=getattr(getattr(transaction_obj, "user", None), "id", None),
        )

        return transaction_obj
