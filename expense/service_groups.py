from decimal import Decimal

from django.db import transaction as db_transaction

from .models import ExpenseGroup, GroupBalance, GroupExpense, GroupExpenseSplit, GroupMember, Settlement
from .service_base import BaseService


class GroupService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def create_group(*, name, created_by, description=""):
        group = ExpenseGroup.objects.create(name=name, description=description, created_by=created_by)
        GroupMember.objects.create(group=group, user=created_by)
        return group

    @staticmethod
    def add_member(*, group, user):
        return GroupMember.objects.get_or_create(group=group, user=user)

    @staticmethod
    def remove_member(*, group, user):
        GroupMember.objects.filter(group=group, user=user).delete()

    @staticmethod
    @db_transaction.atomic
    def create_equal_split_expense(*, group, paid_by, transaction_obj, members):
        expense = GroupExpense.objects.create(group=group, paid_by=paid_by, transaction=transaction_obj)
        share = Decimal(transaction_obj.amount) / Decimal(len(members))

        for member in members:
            GroupExpenseSplit.objects.create(expense=expense, user=member, share_amount=share)
            if member != paid_by:
                GroupService._increase_debt(group=group, debtor=member, creditor=paid_by, amount=share)

        return expense

    @staticmethod
    @db_transaction.atomic
    def create_custom_split_expense(*, group, paid_by, transaction_obj, splits):
        expense = GroupExpense.objects.create(group=group, paid_by=paid_by, transaction=transaction_obj)

        for split in splits:
            GroupExpenseSplit.objects.create(expense=expense, user=split["user"], share_amount=split["amount"])
            if split["user"] != paid_by:
                GroupService._increase_debt(group=group, debtor=split["user"], creditor=paid_by, amount=split["amount"])

        return expense

    @staticmethod
    def _increase_debt(*, group, debtor, creditor, amount):
        balance, _ = GroupBalance.objects.get_or_create(
            group=group,
            from_user=debtor,
            to_user=creditor,
            defaults={"balance_amount": Decimal("0.00")},
        )
        balance.balance_amount += amount
        balance.save(update_fields=["balance_amount"])


class SettlementService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def settle(*, group, payer, receiver, amount, notes=""):
        settlement = Settlement.objects.create(group=group, payer=payer, receiver=receiver, amount=amount, notes=notes)

        try:
            balance = GroupBalance.objects.get(group=group, from_user=payer, to_user=receiver)
            balance.balance_amount -= amount
            if balance.balance_amount <= 0:
                balance.delete()
            else:
                balance.save(update_fields=["balance_amount"])
        except GroupBalance.DoesNotExist:
            pass

        return settlement
