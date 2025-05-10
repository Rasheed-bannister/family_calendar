from flask import Blueprint, jsonify, request, render_template
import threading

from . import database as db
from src.google_integration import tasks_api
from src.main import google_fetch_lock, background_tasks

chores_bp = Blueprint('chores', __name__, url_prefix='/chores')

@chores_bp.route('/update_status/<chore_id>', methods=['POST'])
def update_status(chore_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status or new_status not in ['needsAction', 'completed', 'invisible']:
        return jsonify({'error': 'Invalid status provided'}), 400
    
    try:
        # For local DB updates
        db.update_chore_status(chore_id, new_status)
        
        # For Google Tasks updates - skip invisible as that's local only
        if new_status != 'invisible':
            # Use the dedicated Google Tasks API for updates
            if new_status == 'completed':
                tasks_api.mark_chore_completed(chore_id)
            else:  # needsAction
                tasks_api.update_chore(chore_id, updates={'status': 'needsAction'})
        
        return jsonify({'success': True, 'message': f'Chore {chore_id} status updated to {new_status}'})
    except Exception as e:
        print(f"Error updating chore status: {e}")
        return jsonify({'error': 'Failed to update chore status'}), 500

@chores_bp.route('/refresh', methods=['POST'])
def refresh_chores():
    """Manually trigger a refresh of chores data from Google Tasks"""
    # Start a background task for tasks
    chores_task_id = "tasks"
    
    with google_fetch_lock:
        # Mark as running if not already
        if chores_task_id in background_tasks and background_tasks[chores_task_id]['status'] == 'running':
            return jsonify({'message': 'Refresh already in progress'}), 202
            
        background_tasks[chores_task_id] = {'status': 'running', 'updated': False}
    
    # Start the background task
    from src.google_integration.routes import fetch_google_tasks_background
    chores_thread = threading.Thread(
        target=fetch_google_tasks_background
    )
    chores_thread.daemon = True
    chores_thread.start()
    
    return jsonify({'message': 'Chores refresh started'}), 202

@chores_bp.route('/')
def display_chores():
    # This assumes you fetch chores somewhere to pass to the template
    # Make sure this fetch uses the updated db.get_chores() that filters invisible ones
    chores_list = db.get_chores() # This now filters out 'invisible' chores
    # If chores are rendered as part of another template (like index.html),
    # ensure that template receives the filtered list.
    # This is just an example route if you had a dedicated chores page.
    return render_template('some_template_using_chores.html', chores=chores_list)
