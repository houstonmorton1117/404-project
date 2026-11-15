"""
Admin service helpers for dashboard data and moderation actions.
"""

from models.admin_model import (
    get_all_users,
    set_user_active,
    get_all_listings,
    delete_listing,
    get_admin_storefronts,
    delete_storefront,
    get_admin_returns,
)
from services.notification_service import notify_user
from services.return_service import change_return_status


def fetch_users():
    return get_all_users()


# Replaces remove_user() - Jasmine Mark 11/11/26
def deactivate_user(user_id, acting_user_id):
    if not user_id:
        raise ValueError("User ID required")
    if acting_user_id is not None and int(user_id) == int(acting_user_id):
        raise ValueError("You can't deactivate your own account")
    if not set_user_active(user_id, False):
        raise LookupError("User not found")
    return {"message": "User deactivated successfully"}


def restore_user(user_id):
    if not user_id:
        raise ValueError("User ID required")
    if not set_user_active(user_id, True):
        raise LookupError("User not found")
    return {"message": "User restored successfully"}


def fetch_listings():
    return get_all_listings()


def remove_listing(listing_id):
    if not listing_id:
        raise ValueError("Listing ID required")
    delete_listing(listing_id)
    return {"message": "Listing soft-deleted successfully"}


def fetch_storefronts():
    return get_admin_storefronts()


def remove_storefront(store_id):
    """
    Deletes a storefront from the system.

    Parameters:
        store_id (int): Storefront identifier

    Returns:
        dict: Success message
    """

    # Basic validation to ensure a storefront ID is provided
    if not store_id:
        raise ValueError("Storefront ID required")

    # Call the model to delete the storefront
    delete_storefront(store_id)

    return {"message": "Storefront removed successfully"}


def fetch_returns():
    return get_admin_returns()


def update_return_status_service(return_id, status):
    # Updated 11/14/26 - goes through return_service.change_return_status, which checks the status
    # and, when a return is approved, refunds the order through Stripe first. Problems are raised
    # as ValueError (ReturnError) so the route answers 400 with the message for the admin.
    if not return_id:
        raise ValueError("Return ID required")
    result = change_return_status(return_id, status)
    updated = result["return"]
    refund = result["refund"]

    if refund and refund.get("status") == "already_approved":
        # Saving "approved" again changes nothing, so don't notify the buyer a second time.
        return {**updated, "refund": refund}

    message = f"Your return for order {updated['order_number']} is now {updated['status']}."
    if refund and refund.get("status") == "refunded":
        message = (f"Your return for order {updated['order_number']} was approved and "
                   f"${refund['amount']:.2f} was refunded to your card.")

    # Best-effort: let the buyer know their return moved, but don't fail the
    # admin action if the notification can't be written.
    try:
        notify_user(updated["user_id"], "return", message, link="/account")
    except Exception as e:
        print(f"[admin] return status notification failed: {e}")

    return {**updated, "refund": refund}