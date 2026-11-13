# Showtime
# notification_controller.py - Added by Houston Morton - Iteration 4
#
# HTTP endpoints for the in-app notification bell/tab:
#   GET  /api/notifications            - list the current user's notifications
#   GET  /api/notifications/unread-count
#   POST /api/notifications/<id>/read
#   POST /api/notifications/read-all

from flask import Blueprint, jsonify, session

from services.notification_service import (
    get_notifications_service,
    get_unread_count_service,
    mark_notification_read_service,
    mark_all_read_service,
)

notification_bp = Blueprint("notifications", __name__, url_prefix="/api")


def get_current_user_id():
    user_id = session.get("user_id")
    return int(user_id) if user_id else None


@notification_bp.route("/notifications", methods=["GET"])
def list_notifications():
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify({"notifications": get_notifications_service(user_id)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@notification_bp.route("/notifications/unread-count", methods=["GET"])
def unread_count():
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify({"unread_count": get_unread_count_service(user_id)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@notification_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_read(notification_id):
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify(mark_notification_read_service(notification_id, user_id)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@notification_bp.route("/notifications/read-all", methods=["POST"])
def mark_all_read_route():
    user_id = get_current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        mark_all_read_service(user_id)
        return jsonify({"message": "All notifications marked read."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
