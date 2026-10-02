"""Realtime notification helpers backed by Django Channels."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


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


def notify_group_invitation_created(invitation):
    """Push a realtime notification to the invited user."""
    _send_to_user(
        invitation.invited_user_id,
        {
            "event": "group_invitation.created",
            "invitation_id": str(invitation.id),
            "group_id": str(invitation.group_id),
            "group_name": invitation.group.name,
            "invited_by": invitation.invited_by.get_full_name_or_email()
            if hasattr(invitation.invited_by, "get_full_name_or_email")
            else str(invitation.invited_by),
            "message": f"{invitation.invited_by} invited you to join \"{invitation.group.name}\"",
        },
    )


def notify_group_invitation_response(invitation):
    """Push a realtime notification to the inviter once the invite is answered."""
    _send_to_user(
        invitation.invited_by_id,
        {
            "event": "group_invitation.responded",
            "invitation_id": str(invitation.id),
            "group_id": str(invitation.group_id),
            "group_name": invitation.group.name,
            "status": invitation.status,
            "invited_user": str(invitation.invited_user),
            "message": f"{invitation.invited_user} {invitation.status} your invite to \"{invitation.group.name}\"",
        },
    )
