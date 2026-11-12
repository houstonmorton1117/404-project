# Showtime
# follow_service.py - Added by Houston Morton - Iteration 4

from models.follow_model import (
    follow_storefront,
    unfollow_storefront,
    is_following,
    get_followed_storefronts,
    get_follower_user_ids,
)
from models.storefront_model import get_storefront_by_id


def follow_storefront_service(user_id, storefront_id):
    storefront = get_storefront_by_id(storefront_id)
    if not storefront:
        raise Exception("Storefront not found.")
    if storefront["owner_id"] == user_id:
        raise Exception("You can't follow your own storefront.")
    follow_storefront(user_id, storefront_id)
    return {"following": True}


def unfollow_storefront_service(user_id, storefront_id):
    unfollow_storefront(user_id, storefront_id)
    return {"following": False}


def check_following_service(user_id, storefront_id):
    return {"following": is_following(user_id, storefront_id)}


def get_followed_storefronts_service(user_id):
    return get_followed_storefronts(user_id)


def get_follower_user_ids_service(storefront_id):
    return get_follower_user_ids(storefront_id)
