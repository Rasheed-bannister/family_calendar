from flask import Blueprint, jsonify, request

from src.google_integration import tasks_api
from src.main import background_tasks, google_fetch_lock

from . import database as db

chores_bp = Blueprint("chores", __name__, url_prefix="/chores")


@chores_bp.route("/update_status/<chore_id>", methods=["POST"])
def update_status(chore_id):
    data = request.get_json()
    new_status = data.get("status")
    if not new_status or new_status not in ["needsAction", "completed", "invisible"]:
        return jsonify({"error": "Invalid status provided"}), 400

    try:
        # For local DB updates
        db.update_chore_status(chore_id, new_status)

        # For Google Tasks updates - skip invisible as that's local only
        if new_status != "invisible":
            # Use the dedicated Google Tasks API for updates
            if new_status == "completed":
                tasks_api.mark_chore_completed(chore_id)
            else:  # needsAction
                tasks_api.update_chore(chore_id, updates={"status": "needsAction"})

        return jsonify(
            {
                "success": True,
                "message": f"Chore {chore_id} status updated to {new_status}",
            }
        )
    except Exception as e:
        print(f"Error updating chore status: {e}")
        return jsonify({"error": "Failed to update chore status"}), 500


@chores_bp.route("/refresh", methods=["POST"])
def refresh_chores():
    """Manually trigger a refresh of chores data from Google Tasks"""
    # Start a background task for tasks
    chores_task_id = "tasks"

    with google_fetch_lock:
        # Mark as running if not already
        if (
            chores_task_id in background_tasks
            and background_tasks[chores_task_id]["status"] == "running"
        ):
            return jsonify({"message": "Refresh already in progress"}), 202

        background_tasks[chores_task_id] = {"status": "running", "updated": False}

    # Execute the sync directly instead of in a thread to avoid threading issues
    try:
        from src.google_integration.routes import fetch_google_tasks_background

        fetch_google_tasks_background()  # Call directly without threading
        return jsonify({"message": "Chores refresh completed"}), 200
    except Exception as e:
        print(f"Error during chores refresh: {e}")
        with google_fetch_lock:
            if chores_task_id in background_tasks:
                background_tasks[chores_task_id]["status"] = "error"
        return jsonify({"error": f"Chores refresh failed: {str(e)}"}), 500


@chores_bp.route("/add", methods=["POST"])
def add_chore_route():
    data = request.get_json()
    title = data.get("title")  # This is the person assigned
    notes = data.get("notes")  # This is the chore description

    if not title or not notes:
        return jsonify({"error": "Missing title or notes for the chore"}), 400

    final_chore_id = None
    message = ""

    try:
        # 1. Add to local database
        # db.add_chore expects assigned_to, description
        new_chore_local = db.add_chore(assigned_to=title, description=notes)

        if not new_chore_local:
            # This occurs if db.add_chore returns None (e.g., due to a non-critical IntegrityError
            # like a duplicate UUID, though rare, or if designed to return None on specific failures)
            return (
                jsonify(
                    {
                        "error": "Failed to add chore to local database. It might already exist or another local DB error occurred."
                    }
                ),
                500,
            )

        local_chore_id = new_chore_local.id  # Initially, this is likely a UUID
        final_chore_id = local_chore_id  # Default to local ID

        # 2. Add to Google Tasks
        # tasks_api.create_chore expects title (for task title) and details (for task notes)
        google_task = tasks_api.create_chore(title=title, details=notes)

        if google_task and google_task.get("id"):
            google_task_id = google_task.get("id")
            db.update_chore_google_id(local_chore_id, google_task_id)
            final_chore_id = google_task_id  # The chore ID is now the Google ID
            message = "Chore added successfully and synced with Google Tasks."
        else:
            # Google Task creation failed or didn't return an ID.
            # The chore is added locally with its initial (e.g., UUID) ID.
            message = "Chore added locally, but failed to sync with Google Tasks. It will retain a local ID."
            # No error status, but the message indicates partial success.

        return (
            jsonify(
                {
                    "success": True,
                    "message": message,
                    "id": final_chore_id,  # Return the final ID of the chore
                }
            ),
            201,
        )

    except Exception as e:
        # This will catch errors from db.add_chore (if it raises an exception not handled by returning None),
        # tasks_api.create_chore, or db.update_chore_google_id.
        print(f"Error in add_chore_route: {e}")
        # Attempt to be more specific if possible, otherwise a general error.
        # If new_chore_local was created but a subsequent step failed, it remains in the local DB with its initial ID.
        return (
            jsonify(
                {
                    "error": "Failed to add chore due to an internal server error.",
                    "details": str(e),
                }
            ),
            500,
        )
