from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import ExpenseGroup, GroupBalance, GroupExpense, GroupExpenseSplit, GroupInvitation, GroupMember, Settlement
from .base import BaseService, ServiceError
from .notifications import notify_group_invitation_created, notify_group_invitation_response


class GroupService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def create_group(*, name, created_by, description=""):
        group = ExpenseGroup.objects.create(name=name, description=description, created_by=created_by)
        GroupMember.objects.create(group=group, user=created_by)
        return group

    @staticmethod
    def remove_member(*, group, user):
        GroupMember.objects.filter(group=group, user=user).delete()

    @staticmethod
    def _validate_split_members(group, members):
        valid_member_ids = set(group.members.values_list("user_id", flat=True))
        member_list = list(dict.fromkeys(members))
        for member in member_list:
            if member.id not in valid_member_ids:
                raise ServiceError("Split member is not part of the group.")
        return member_list

    @staticmethod
    def _validate_payer(group, paid_by):
        if not group.members.filter(user=paid_by).exists():
            raise ServiceError("The payer must be a member of the group.")

    @staticmethod
    def _increase_debt(*, group, debtor, creditor, amount):
        if debtor == creditor:
            return

        amount = Decimal(amount)
        if amount <= 0:
            return

        reverse_balance = GroupBalance.objects.filter(
            group=group,
            from_user=creditor,
            to_user=debtor,
        ).first()

        if reverse_balance is not None:
            remaining = reverse_balance.balance_amount - amount
            if remaining > 0:
                reverse_balance.balance_amount = remaining
                reverse_balance.save(update_fields=["balance_amount"])
                return
            reverse_balance.delete()
            amount = abs(remaining)

        balance, _ = GroupBalance.objects.get_or_create(
            group=group,
            from_user=debtor,
            to_user=creditor,
            defaults={"balance_amount": Decimal("0.00")},
        )
        balance.balance_amount += amount
        balance.save(update_fields=["balance_amount"])

    @staticmethod
    @db_transaction.atomic
    def create_equal_split_expense(*, group, paid_by, transaction_obj, members):
        member_list = GroupService._validate_split_members(group, members)
        if not member_list:
            raise ServiceError("At least one group member is required for the split.")
        GroupService._validate_payer(group, paid_by)

        total = Decimal(str(transaction_obj.amount))
        expense = GroupExpense.objects.create(group=group, paid_by=paid_by, transaction=transaction_obj)

        base_cents, remainder_cents = divmod(int(total * 100), len(member_list))
        for index, member in enumerate(member_list):
            share = Decimal(base_cents + (index < remainder_cents)) / Decimal(100)
            GroupExpenseSplit.objects.create(expense=expense, user=member, share_amount=share)
            if member != paid_by:
                GroupService._increase_debt(group=group, debtor=member, creditor=paid_by, amount=share)

        return expense

    @staticmethod
    @db_transaction.atomic
    def create_custom_split_expense(*, group, paid_by, transaction_obj, splits):
        if not splits:
            raise ServiceError("At least one custom share is required.")
        GroupService._validate_payer(group, paid_by)

        normalized = []
        seen_users = set()
        for split in splits:
            user = split["user"]
            amount = Decimal(str(split["amount"]))
            if user.id in seen_users:
                raise ServiceError("A user cannot appear more than once in a custom split.")
            if user.id not in set(group.members.values_list("user_id", flat=True)):
                raise ServiceError("Split member is not part of the group.")
            seen_users.add(user.id)
            normalized.append({"user": user, "amount": amount})

        total = sum((split["amount"] for split in normalized), Decimal("0.00"))
        if total != Decimal(str(transaction_obj.amount)):
            raise ServiceError("Custom split total must match the transaction amount.")

        expense = GroupExpense.objects.create(group=group, paid_by=paid_by, transaction=transaction_obj)

        for split in normalized:
            GroupExpenseSplit.objects.create(expense=expense, user=split["user"], share_amount=split["amount"])
            if split["user"] != paid_by:
                GroupService._increase_debt(group=group, debtor=split["user"], creditor=paid_by, amount=split["amount"])

        return expense

    @staticmethod
    @db_transaction.atomic
    def split_existing_transaction(*, transaction_obj, group, paid_by, split_mode, splits=None):
        if transaction_obj.is_deleted:
            raise ServiceError("Deleted transactions cannot be split.")
        if transaction_obj.entry_type != "debit" or transaction_obj.category.category_type == "transfer":
            raise ServiceError("Only expense transactions can be split.")
        if transaction_obj.is_group_expense or GroupExpense.objects.filter(transaction=transaction_obj).exists():
            raise ServiceError("This transaction has already been split.")

        if split_mode == "equal":
            expense = GroupService.create_equal_split_expense(
                group=group,
                paid_by=paid_by,
                transaction_obj=transaction_obj,
                members=[member.user for member in group.members.select_related("user")],
            )
        elif split_mode == "custom":
            expense = GroupService.create_custom_split_expense(
                group=group,
                paid_by=paid_by,
                transaction_obj=transaction_obj,
                splits=splits or [],
            )
        else:
            raise ServiceError("Choose an equal or custom split.")

        transaction_obj.is_group_expense = True
        transaction_obj.save(update_fields=["is_group_expense", "updated_at"])
        return expense


class GroupInvitationService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def invite_member(*, group, invited_user, invited_by):
        if invited_user == invited_by:
            raise ServiceError("You cannot invite yourself to the group.")

        if GroupMember.objects.filter(group=group, user=invited_user).exists():
            raise ServiceError(f"{invited_user} is already a member of this group.")

        if GroupInvitation.objects.filter(
            group=group, invited_user=invited_user, status=GroupInvitation.Status.PENDING
        ).exists():
            raise ServiceError(f"{invited_user} already has a pending invite to this group.")

        invitation = GroupInvitation.objects.create(
            group=group,
            invited_user=invited_user,
            invited_by=invited_by,
            status=GroupInvitation.Status.PENDING,
        )
        notify_group_invitation_created(invitation)
        return invitation

    @staticmethod
    @db_transaction.atomic
    def accept_invitation(*, invitation, user):
        if invitation.invited_user_id != user.id:
            raise ServiceError("You are not authorized to respond to this invitation.")
        if invitation.status != GroupInvitation.Status.PENDING:
            raise ServiceError("This invitation has already been responded to.")

        invitation.status = GroupInvitation.Status.ACCEPTED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at", "updated_at"])

        GroupMember.objects.get_or_create(group=invitation.group, user=user)
        notify_group_invitation_response(invitation)
        return invitation

    @staticmethod
    @db_transaction.atomic
    def decline_invitation(*, invitation, user):
        if invitation.invited_user_id != user.id:
            raise ServiceError("You are not authorized to respond to this invitation.")
        if invitation.status != GroupInvitation.Status.PENDING:
            raise ServiceError("This invitation has already been responded to.")

        invitation.status = GroupInvitation.Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at", "updated_at"])

        notify_group_invitation_response(invitation)
        return invitation


class SettlementService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def settle(*, group, payer, receiver, amount, notes=""):
        if payer == receiver:
            raise ServiceError("Payer and receiver must be different users.")

        amount = Decimal(str(amount))
        if amount <= 0:
            raise ServiceError("Settlement amount must be greater than zero.")

        balance = GroupBalance.objects.filter(group=group, from_user=payer, to_user=receiver).first()
        if balance is None:
            raise ServiceError("No outstanding balance found for this settlement.")

        if amount > balance.balance_amount:
            raise ServiceError("Settlement amount exceeds the outstanding balance.")

        settlement = Settlement.objects.create(group=group, payer=payer, receiver=receiver, amount=amount, notes=notes)

        balance.balance_amount -= amount
        if balance.balance_amount <= 0:
            balance.delete()
        else:
            balance.save(update_fields=["balance_amount"])

        return settlement
