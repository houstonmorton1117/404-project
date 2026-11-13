# Showtime
# notification_service.py - Added by Houston Morton - Iteration 4
#
# Purpose: creates and reads in-app notifications. notify_user() is the single
# entry point other services call (checkout, returns, new listings) so every
# notification goes through the same validation and storage path.

from models.notification_model import (
    create_notification,
    get_notifications_for_user,
    get_unread_count,
    mark_notification_read,
    mark_all_read,
)

VALID_TYPES = {"order", "return", "new_listing"}


def notify_user(user_id, type, message, link=None, conn=None):
    """Best-effort notification create. Callers that trigger this from inside a
    larger transaction (e.g. checkout) should not let a failure here roll back
    unrelated work - catch exceptions at the call site if needed."""
    if not user_id or type not in VALID_TYPES or not message:
        return None
    return create_notification(user_id, type, message, link=link, conn=conn)


def get_notifications_service(user_id):
    if not user_id:
        raise Exception("Unauthorized.")
    return get_notifications_for_user(user_id)


def get_unread_count_service(user_id):
    if not user_id:
        raise Exception("Unauthorized.")
    return get_unread_count(user_id)


def mark_notification_read_service(notification_id, user_id):
    if not user_id:
        raise Exception("Unauthorized.")
    updated = mark_notification_read(notification_id, user_id)
    if updated is None:
        raise Exception("Notification not found.")
    return updated


def mark_all_read_service(user_id):
    if not user_id:
        raise Exception("Unauthorized.")
    mark_all_read(user_id)
