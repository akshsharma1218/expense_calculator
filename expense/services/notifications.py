"""Realtime notification helpers backed by Django Channels."""

from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from ..models import UserNotification


def _user_group_name(user_id):
    return f"user_{user_id}"


def _send_to_user(user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        _user_group_name(user_id),
        {"type": "notify", "payload": payload},
    )


def create_user_notification(*, user_id, event, message, data=None):
    """Persist a notification for one week and publish it after commit."""
    notification_data = data or {}
    notification = UserNotification.objects.create(
        user_id=user_id,
        event=event,
        message=message,
        data=notification_data,
        expires_at=timezone.now() + timedelta(days=7),
    )
    payload = {
        **notification_data,
        "event": notification.event,
        "notification_id": str(notification.pk),
        "message": notification.message,
        "created_at": notification.created_at.isoformat(),
        "expires_at": notification.expires_at.isoformat(),
    }
    transaction.on_commit(lambda: _send_to_user(user_id, payload))
    return notification


def notify_group_invitation_created(invitation):
    """Push a realtime notification to the invited user."""
    inviter = (
        invitation.invited_by.get_full_name_or_email()
        if hasattr(invitation.invited_by, "get_full_name_or_email")
        else str(invitation.invited_by)
    )
    create_user_notification(
        user_id=invitation.invited_user_id,
        event="group_invitation.created",
        message=f'{inviter} invited you to join "{invitation.group.name}"',
        data={
            "invitation_id": str(invitation.id),
            "group_id": str(invitation.group_id),
            "group_name": invitation.group.name,
            "invited_by": inviter,
        },
    )


def notify_group_invitation_response(invitation):
    """Push a realtime notification to the inviter once the invite is answered."""
    invited_user = str(invitation.invited_user)
    create_user_notification(
        user_id=invitation.invited_by_id,
        event="group_invitation.responded",
        message=f'{invited_user} {invitation.status} your invite to "{invitation.group.name}"',
        data={
            "invitation_id": str(invitation.id),
            "group_id": str(invitation.group_id),
            "group_name": invitation.group.name,
            "status": invitation.status,
            "invited_user": invited_user,
        },
    )


def notify_group_expense_split(*, user_id, group, payer, expense, share_amount):
    payer_name = str(payer)
    description = expense.transaction.description or "a group expense"
    create_user_notification(
        user_id=user_id,
        event="group_expense.split",
        message=(
            f'{payer_name} added you to "{group.name}" for {description} '
            f"(₹{share_amount:.2f})"
        ),
        data={
            "group_id": str(group.pk),
            "group_name": group.name,
            "payer": payer_name,
            "amount": str(share_amount),
        },
    )


def notify_group_settlement_paid(settlement):
    payer_name = str(settlement.payer)
    create_user_notification(
        user_id=settlement.receiver_id,
        event="group_settlement.paid",
        message=(
            f'{payer_name} recorded a payment of ₹{settlement.amount:.2f} '
            f'for "{settlement.group.name}"'
        ),
        data={
            "group_id": str(settlement.group_id),
            "group_name": settlement.group.name,
            "settlement_id": str(settlement.pk),
            "payer": payer_name,
            "amount": str(settlement.amount),
        },
    )


def notify_group_settlement_received(settlement):
    receiver_name = str(settlement.receiver)
    create_user_notification(
        user_id=settlement.payer_id,
        event="group_settlement.received",
        message=(
            f'{receiver_name} recorded your ₹{settlement.amount:.2f} payment '
            f'for "{settlement.group.name}"'
        ),
        data={
            "group_id": str(settlement.group_id),
            "group_name": settlement.group.name,
            "settlement_id": str(settlement.pk),
            "receiver": receiver_name,
            "amount": str(settlement.amount),
        },
    )


def notify_group_member_removed(*, user_id, group, removed_by):
    create_user_notification(
        user_id=user_id,
        event="group_member.removed",
        message=f'{removed_by} removed you from "{group.name}"',
        data={
            "group_id": str(group.pk),
            "group_name": group.name,
            "removed_by": str(removed_by),
        },
    )
