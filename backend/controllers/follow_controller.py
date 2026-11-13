# Showtime
# follow_controller.py - Added by Houston Morton - Iteration 4
#
# HTTP endpoints for following a storefront:
#   POST   /api/storefronts/<id>/follow
#   DELETE /api/storefronts/<id>/follow
#   GET    /api/storefronts/<id>/follow/check
#   GET    /api/account/following

from flask import Blueprint, jsonify, session

from services.follow_service import (
    follow_storefront_service,
    unfollow_storefront_service,
    check_following_service,
    get_followed_storefronts_service,
)

follow_bp = Blueprint("follow", __name__, url_prefix="/api")


def get_current_user_id():
    user_id = session.get("user_id")
    return int(user_id) if user_id else None


@follow_bp.route("/storefronts/<int:storefront_id>/follow", methods=["POST"])
def follow_route(storefront_id):
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify(follow_storefront_service(user_id, storefront_id)), 200
    except Exception as e:
        msg = str(e).lower()
        status = 404 if "not found" in msg else 400
        return jsonify({"error": str(e)}), status


@follow_bp.route("/storefronts/<int:storefront_id>/follow", methods=["DELETE"])
def unfollow_route(storefront_id):
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify(unfollow_storefront_service(user_id, storefront_id)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@follow_bp.route("/storefronts/<int:storefront_id>/follow/check", methods=["GET"])
def check_follow_route(storefront_id):
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"following": False}), 200
    return jsonify(check_following_service(user_id, storefront_id)), 200


@follow_bp.route("/account/following", methods=["GET"])
def get_following_route():
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"following": get_followed_storefronts_service(user_id)}), 200
