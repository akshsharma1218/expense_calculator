from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import F, Q
from django.utils import timezone

from ..models import (
    Account,
    Category,
    EntryType,
    ExpenseGroup,
    GroupBalance,
    GroupExpense,
    GroupExpenseSplit,
    GroupInvitation,
    GroupMember,
    Settlement,
    SettlementAllocation,
    Transaction,
    UserNotification,
)
from .base import BaseService, ServiceError
from .notifications import (
    notify_group_expense_split,
    notify_group_invitation_created,
    notify_group_invitation_response,
    notify_group_member_removed,
    notify_group_settlement_paid,
    notify_group_settlement_received,
)


class GroupService(BaseService):
    @staticmethod
    @db_transaction.atomic
    def create_group(*, name, created_by, description=""):
        group = ExpenseGroup.objects.create(name=name, description=description, created_by=created_by)
        GroupMember.objects.create(group=group, user=created_by)
        return group

    @staticmethod
    @db_transaction.atomic
    def delete_group(*, group, deleted_by):
        locked_group = ExpenseGroup.objects.select_for_update().get(pk=group.pk)
        if locked_group.created_by_id != deleted_by.id:
            raise ServiceError("Only the group creator can delete this group.")

        transaction_ids = GroupExpense.objects.filter(
            group=locked_group,
        ).values_list("transaction_id", flat=True)
        Transaction.objects.filter(pk__in=transaction_ids).update(
            is_group_expense=False,
        )
        UserNotification.objects.filter(
            data__group_id=str(locked_group.pk),
        ).delete()
        locked_group.delete()

    @staticmethod
    @db_transaction.atomic
    def remove_member(*, group, user, removed_by):
        if removed_by.id != group.created_by_id:
            raise ServiceError("Only the group creator can remove members.")
        if user.id == group.created_by_id:
            raise ServiceError("The group creator cannot be removed.")
        if not GroupMember.objects.filter(group=group, user=user).exists():
            raise ServiceError("This user is not a member of the group.")

        has_open_split = GroupExpenseSplit.objects.filter(
            expense__group=group,
            status=GroupExpenseSplit.Status.PENDING,
        ).exclude(
            user=F("expense__paid_by"),
        ).filter(
            Q(user=user) | Q(expense__paid_by=user),
        ).exists()
        has_balance = GroupBalance.objects.filter(group=group).filter(
            Q(from_user=user) | Q(to_user=user),
        ).exists()
        if has_open_split or has_balance:
            raise ServiceError(
                "Settle all outstanding group balances before removing this member."
            )

        GroupMember.objects.filter(group=group, user=user).delete()
        notify_group_member_removed(
            user_id=user.id,
            group=group,
            removed_by=removed_by,
        )

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
            if remaining >= 0:
                if remaining == 0:
                    reverse_balance.delete()
                    return
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
                notify_group_expense_split(
                    user_id=member.id,
                    group=group,
                    payer=paid_by,
                    expense=expense,
                    share_amount=share,
                )

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
            if user == paid_by:
                raise ServiceError("The payer's share is calculated automatically.")
            if user.id not in set(group.members.values_list("user_id", flat=True)):
                raise ServiceError("Split member is not part of the group.")
            if amount <= 0:
                raise ServiceError("Each owed amount must be greater than zero.")
            seen_users.add(user.id)
            normalized.append({"user": user, "amount": amount})

        total = sum((split["amount"] for split in normalized), Decimal("0.00"))
        transaction_total = Decimal(str(transaction_obj.amount))
        if total > transaction_total:
            raise ServiceError("Amounts owed cannot exceed the transaction amount.")

        expense = GroupExpense.objects.create(group=group, paid_by=paid_by, transaction=transaction_obj)

        payer_share = transaction_total - total
        if payer_share > 0:
            GroupExpenseSplit.objects.create(
                expense=expense,
                user=paid_by,
                share_amount=payer_share,
            )

        for split in normalized:
            GroupExpenseSplit.objects.create(expense=expense, user=split["user"], share_amount=split["amount"])
            GroupService._increase_debt(group=group, debtor=split["user"], creditor=paid_by, amount=split["amount"])
            notify_group_expense_split(
                user_id=split["user"].id,
                group=group,
                payer=paid_by,
                expense=expense,
                share_amount=split["amount"],
            )

        return expense

    @staticmethod
    @db_transaction.atomic
    def split_existing_transaction(*, transaction_obj, group, paid_by, split_mode, splits=None):
        if transaction_obj.is_deleted:
            raise ServiceError("Deleted transactions cannot be split.")
        if transaction_obj.entry_type != "debit" or transaction_obj.category.category_type == "transfer":
            raise ServiceError("Only expense transactions can be split.")
        if GroupExpense.objects.filter(transaction=transaction_obj).exists():
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

    @staticmethod
    @db_transaction.atomic
    def update_split_expense(*, transaction_obj, group, paid_by, split_mode, splits=None):
        if transaction_obj.is_deleted:
            raise ServiceError("Deleted transactions cannot be split.")
        if transaction_obj.entry_type != EntryType.DEBIT or transaction_obj.category.category_type == Category.CategoryType.TRANSFER:
            raise ServiceError("Only expense transactions can be split.")

        expense = (
            GroupExpense.objects.select_for_update()
            .filter(transaction=transaction_obj, paid_by=paid_by)
            .first()
        )
        if expense is None:
            raise ServiceError("This transaction does not have a split you can update.")
        if expense.group_id != group.pk:
            raise ServiceError("An existing split must remain in its original group.")

        old_splits = list(
            GroupExpenseSplit.objects.select_for_update()
            .filter(expense=expense)
            .order_by("created_at")
        )
        if any(
            split.status != GroupExpenseSplit.Status.PENDING
            or SettlementAllocation.objects.filter(split=split).exists()
            for split in old_splits
        ):
            raise ServiceError("A split with recorded settlement activity cannot be changed.")

        GroupService._validate_payer(group, paid_by)
        transaction_total = Decimal(str(transaction_obj.amount))
        normalized = []
        if split_mode == "equal":
            members = GroupService._validate_split_members(
                group,
                [member.user for member in group.members.select_related("user")],
            )
            if not members:
                raise ServiceError("At least one group member is required for the split.")
            base_cents, remainder_cents = divmod(int(transaction_total * 100), len(members))
            normalized = [
                {
                    "user": member,
                    "amount": Decimal(base_cents + (index < remainder_cents)) / Decimal(100),
                }
                for index, member in enumerate(members)
            ]
        elif split_mode == "custom":
            if not splits:
                raise ServiceError("At least one custom share is required.")
            seen_users = set()
            valid_member_ids = set(group.members.values_list("user_id", flat=True))
            for split in splits:
                user = split["user"]
                amount = Decimal(str(split["amount"]))
                if user.id in seen_users:
                    raise ServiceError("A user cannot appear more than once in a custom split.")
                if user == paid_by:
                    raise ServiceError("The payer's share is calculated automatically.")
                if user.id not in valid_member_ids:
                    raise ServiceError("Split member is not part of the group.")
                if amount <= 0:
                    raise ServiceError("Each owed amount must be greater than zero.")
                seen_users.add(user.id)
                normalized.append({"user": user, "amount": amount})
            if sum((share["amount"] for share in normalized), Decimal("0.00")) > transaction_total:
                raise ServiceError("Amounts owed cannot exceed the transaction amount.")
        else:
            raise ServiceError("Choose an equal or custom split.")

        old_group = expense.group
        for old_split in old_splits:
            if old_split.user_id != expense.paid_by_id:
                GroupService._increase_debt(
                    group=old_group,
                    debtor=expense.paid_by,
                    creditor=old_split.user,
                    amount=old_split.share_amount,
                )
        GroupExpenseSplit.objects.filter(pk__in=[split.pk for split in old_splits]).delete()

        expense.group = group
        expense.save(update_fields=["group", "updated_at"])
        if split_mode == "equal":
            shares = normalized
        else:
            owed_total = sum(
                (share["amount"] for share in normalized),
                Decimal("0.00"),
            )
            payer_share = transaction_total - owed_total
            shares = [
                *(
                    [{"user": paid_by, "amount": payer_share}]
                    if payer_share > 0
                    else []
                ),
                *normalized,
            ]

        for share in shares:
            GroupExpenseSplit.objects.create(
                expense=expense,
                user=share["user"],
                share_amount=share["amount"],
            )
            if share["user"] != paid_by:
                GroupService._increase_debt(
                    group=group,
                    debtor=share["user"],
                    creditor=paid_by,
                    amount=share["amount"],
                )
                notify_group_expense_split(
                    user_id=share["user"].id,
                    group=group,
                    payer=paid_by,
                    expense=expense,
                    share_amount=share["amount"],
                )
        return expense

    @staticmethod
    @db_transaction.atomic
    def delete_group_expense(*, transaction_obj):
        expense = (
            GroupExpense.objects.select_for_update()
            .filter(transaction=transaction_obj)
            .first()
        )
        if expense is None:
            return

        splits = list(
            GroupExpenseSplit.objects.select_for_update()
            .filter(expense=expense)
            .select_related("user")
        )
        if any(
            split.status != GroupExpenseSplit.Status.PENDING
            or SettlementAllocation.objects.filter(split=split).exists()
            for split in splits
        ):
            raise ServiceError(
                "This transaction has settled shares and cannot be deleted."
            )

        for split in splits:
            if split.user_id == expense.paid_by_id:
                continue
            GroupService._increase_debt(
                group=expense.group,
                debtor=expense.paid_by,
                creditor=split.user,
                amount=split.share_amount,
            )
        expense.delete()


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
    def settle(*, group, payer, receiver, account: Account, split_ids, notes=""):
        if payer == receiver:
            raise ServiceError("Payer and receiver must be different.")
        if account.user_id != payer.id:
            raise ServiceError("Choose one of your own accounts.")
        if not account.is_active:
            raise ServiceError("The selected account is inactive.")
        if not group.members.filter(user=payer).exists():
            raise ServiceError("The payer must be a group member.")
        if not group.members.filter(user=receiver).exists():
            raise ServiceError("The receiver must be a group member.")

        selected_ids = list(dict.fromkeys(split_ids))
        if not selected_ids:
            raise ServiceError("Select at least one expense share to settle.")

        splits = list(
            GroupExpenseSplit.objects.select_for_update()
            .filter(
                pk__in=selected_ids,
                expense__group=group,
                expense__paid_by=receiver,
                user=payer,
                status=GroupExpenseSplit.Status.PENDING,
            )
            .exclude(user=receiver)
        )
        if len(splits) != len(selected_ids):
            raise ServiceError("One or more selected shares are no longer payable.")

        split_amounts = []
        for split in splits:
            allocated = sum(
                SettlementAllocation.objects.filter(split=split)
                .values_list("amount", flat=True),
                Decimal("0.00"),
            )
            outstanding = split.share_amount - allocated
            if outstanding <= 0:
                raise ServiceError("One or more selected shares are already settled.")
            split_amounts.append((split, outstanding))

        amount = sum(
            (outstanding for _, outstanding in split_amounts),
            Decimal("0.00"),
        )
        if amount <= 0:
            raise ServiceError("The selected shares have no outstanding amount.")
        settlement = Settlement.objects.create(
            group=group,
            payer=payer,
            receiver=receiver,
            amount=amount,
            notes=notes,
        )

        from .transactions import TransactionService

        debit_category, _ = Category.objects.get_or_create(
            name="Group Settlement Paid",
            category_type=Category.CategoryType.EXPENSE,
            is_system=True,
            created_by=None,
            defaults={"normal_side": EntryType.DEBIT},
        )
        payer_transaction = TransactionService.create_transaction(
            user=payer,
            account=account,
            category=debit_category,
            amount=amount,
            transaction_date=settlement.settlement_date,
            description=f"Group settlement paid to {receiver} ({group.name})",
        )
        settlement.payer_transaction = payer_transaction
        settlement.save(update_fields=["payer_transaction", "updated_at"])

        SettlementAllocation.objects.bulk_create(
            [
                SettlementAllocation(
                    settlement=settlement,
                    split=split,
                    amount=outstanding,
                )
                for split, outstanding in split_amounts
            ]
        )
        GroupExpenseSplit.objects.filter(
            pk__in=[split.pk for split, _ in split_amounts]
        ).update(status=GroupExpenseSplit.Status.SETTLED)
        GroupService._increase_debt(
            group=group,
            debtor=receiver,
            creditor=payer,
            amount=amount,
        )
        notify_group_settlement_paid(settlement)
        return settlement

    @staticmethod
    @db_transaction.atomic
    def record_received(*, settlement, receiver, account):
        locked_settlement = Settlement.objects.select_for_update().get(pk=settlement.pk)
        if locked_settlement.receiver_id != receiver.id:
            raise ServiceError("Only the settlement receiver can record this payment.")
        if locked_settlement.receiver_transaction_id:
            raise ServiceError("The received payment has already been recorded.")
        if account.user_id != receiver.id:
            raise ServiceError("Choose one of your own accounts.")
        if not account.is_active:
            raise ServiceError("The selected account is inactive.")

        from .transactions import TransactionService

        credit_category, _ = Category.objects.get_or_create(
            name="Group Settlement Received",
            category_type=Category.CategoryType.INCOME,
            is_system=True,
            created_by=None,
            defaults={"normal_side": EntryType.CREDIT},
        )
        receiver_transaction = TransactionService.create_transaction(
            user=receiver,
            account=account,
            category=credit_category,
            amount=locked_settlement.amount,
            transaction_date=locked_settlement.settlement_date,
            description=f"Group settlement received from {locked_settlement.payer} "
            f"({locked_settlement.group.name})",
        )
        locked_settlement.receiver_transaction = receiver_transaction
        locked_settlement.save(
            update_fields=["receiver_transaction", "updated_at"]
        )
        notify_group_settlement_received(locked_settlement)
        return receiver_transaction
