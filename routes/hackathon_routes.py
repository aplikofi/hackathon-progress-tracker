from flask import Blueprint, render_template, request, redirect, url_for, session, Response, jsonify
from extensions import db
from models import Hackathon, Task, Note, Attachment, ParticipatedEvent
from services.devpost_service import fetch_india_hackathons, fetch_global_hackathons
from services.storage_service import delete_file_content, move_file_to_participated_bucket
import csv
from io import StringIO
import logging

logger = logging.getLogger(__name__)

hackathon_bp = Blueprint('hackathon', __name__)

def _is_ajax():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('ajax') == 'true'

@hackathon_bp.route('/')
def index():
    if not session.get('authenticated'):
        return render_template('login.html')
    
    active_tab = request.args.get('tab', 'tracker')
    
    # Data for the active tab
    hackathons = []
    india_events = []
    global_events = []
    participated_events = []
    india_page = 1
    global_page = 1
    db_error = None
    
    try:
        if active_tab == 'tracker':
            hackathons = Hackathon.query.order_by(Hackathon.id.desc()).all()
        elif active_tab == 'upcoming':
            india_page = request.args.get('india_page', 1, type=int)
            global_page = request.args.get('global_page', 1, type=int)
            india_page = max(1, india_page)
            global_page = max(1, global_page)
            
            from services.devpost_service import fetch_upcoming_events
            india_events, global_events = fetch_upcoming_events(
                india_page=india_page,
                global_page=global_page
            )
        elif active_tab == 'participated':
            participated_events = ParticipatedEvent.query.order_by(ParticipatedEvent.id.desc()).all()
        else:
            active_tab = 'tracker'
            hackathons = Hackathon.query.order_by(Hackathon.id.desc()).all()
    except Exception as e:
        err_msg = str(e).lower()
        logger.error(f"Error loading tab '{active_tab}': {e}", exc_info=True)
        db.session.rollback()
        
        # Self-healing: If an UndefinedColumn error occurred, run migration and retry query once
        if 'does not exist' in err_msg or 'undefinedcolumn' in err_msg or 'no such column' in err_msg:
            try:
                logger.info("Missing column detected. Triggering self-healing database migration...")
                from app import auto_migrate_db
                auto_migrate_db(db.engine)
                if active_tab == 'participated':
                    participated_events = ParticipatedEvent.query.order_by(ParticipatedEvent.id.desc()).all()
                else:
                    hackathons = Hackathon.query.order_by(Hackathon.id.desc()).all()
                logger.info(f"Self-healing migration succeeded! Loaded {len(hackathons or participated_events)} entries.")
                db_error = None
            except Exception as retry_err:
                logger.error(f"Auto-recovery retry failed: {retry_err}", exc_info=True)
                db.session.rollback()
                db_error = f"Database schema sync error: {retry_err}"
        else:
            db_error = f"Database query error: {e}"
    
    return render_template('dashboard.html',
                           active_tab=active_tab,
                           hackathons=hackathons,
                           india_events=india_events,
                           global_events=global_events,
                           participated_events=participated_events,
                           india_page=india_page,
                           global_page=global_page,
                           db_error=db_error)

@hackathon_bp.route('/add_hackathon', methods=['POST'])
def add_hackathon():
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        event_type = request.form.get('event_type', 'online').strip()
        prize_amount = request.form.get('prize_amount', '').strip()
        idea = request.form.get('idea', '').strip()
        date = request.form.get('date', '').strip()
        result_date = request.form.get('result_date', '').strip()
        url = request.form.get('url', '').strip()
        registered = request.form.get('registered') in ['true', 'True', '1', 'on']
        is_idea_submission = request.form.get('is_idea_submission') in ['true', 'True', '1', 'on']
        header_note = request.form.get('header_note', '').strip()
        
        # Ensure URL has protocol if provided
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        task_titles = request.form.getlist('tasks[]')
        if not task_titles:
            task_titles = request.form.getlist('tasks')
            
        if name:
            hackathon = Hackathon(
                name=name,
                location=location if location else None,
                event_type=event_type if event_type in ['online', 'offline'] else 'online',
                prize_amount=prize_amount if prize_amount else None,
                idea=idea if idea else None,
                description=idea if idea else None,
                date=date if date else None,
                result_date=result_date if result_date else None,
                url=url if url else None,
                registered=registered,
                is_idea_submission=is_idea_submission,
                header_note=header_note if header_note else None,
                progress=0
            )
            db.session.add(hackathon)
            db.session.flush()  # get hackathon.id
            
            for title in task_titles:
                title_clean = title.strip()
                if title_clean:
                    task = Task(hackathon_id=hackathon.id, title=title_clean, completed=False)
                    db.session.add(task)
            
            hackathon.update_progress()
            db.session.commit()
            logger.info(f"Added new hackathon '{name}' with {len(task_titles)} tasks.")
    except Exception as e:
        logger.error(f"Failed to add hackathon: {e}")
        db.session.rollback()
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/edit_hackathon/<int:hackathon_id>', methods=['POST'])
def edit_hackathon(hackathon_id):
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        hackathon = Hackathon.query.get(hackathon_id)
        if hackathon:
            name = request.form.get('name', '').strip()
            location = request.form.get('location', '').strip()
            event_type = request.form.get('event_type', 'online').strip()
            prize_amount = request.form.get('prize_amount', '').strip()
            idea = request.form.get('idea', '').strip()
            date = request.form.get('date', '').strip()
            result_date = request.form.get('result_date', '').strip()
            url = request.form.get('url', '').strip()
            registered = request.form.get('registered') in ['true', 'True', '1', 'on']
            is_idea_submission = request.form.get('is_idea_submission') in ['true', 'True', '1', 'on']
            header_note = request.form.get('header_note', '').strip()
            
            if url and not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                
            if name:
                hackathon.name = name
                hackathon.location = location if location else None
                hackathon.event_type = event_type if event_type in ['online', 'offline'] else 'online'
                hackathon.prize_amount = prize_amount if prize_amount else None
                hackathon.idea = idea if idea else None
                hackathon.description = idea if idea else None
                hackathon.date = date if date else None
                hackathon.result_date = result_date if result_date else None
                hackathon.url = url if url else None
                hackathon.registered = registered
                hackathon.is_idea_submission = is_idea_submission
                hackathon.header_note = header_note if header_note else None
                
                db.session.commit()
                logger.info(f"Updated hackathon ID {hackathon_id} successfully.")
    except Exception as e:
        logger.error(f"Failed to edit hackathon ID {hackathon_id}: {e}")
        db.session.rollback()
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/toggle_task/<int:task_id>', methods=['POST'])
def toggle_task(task_id):
    if not session.get('authenticated'):
        if _is_ajax():
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('hackathon.index'))
    
    try:
        task = Task.query.get(task_id)
        if not task:
            if _is_ajax():
                return jsonify({'error': 'Task not found'}), 404
            return redirect(url_for('hackathon.index', tab='tracker'))
            
        task.completed = not task.completed
        hackathon = task.hackathon
        progress = hackathon.update_progress()
        db.session.commit()
        
        if _is_ajax():
            completed_count = sum(1 for t in hackathon.tasks if t.completed)
            total_count = len(hackathon.tasks)
            return jsonify({
                'success': True,
                'task_id': task.id,
                'completed': task.completed,
                'hackathon_id': hackathon.id,
                'progress': progress,
                'completed_count': completed_count,
                'total_count': total_count
            })
    except Exception as e:
        logger.error(f"Failed to toggle task ID {task_id}: {e}")
        db.session.rollback()
        if _is_ajax():
            return jsonify({'error': str(e)}), 500
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/add_task/<int:hackathon_id>', methods=['POST'])
def add_task(hackathon_id):
    if not session.get('authenticated'):
        if _is_ajax():
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('hackathon.index'))
    
    try:
        title = request.form.get('title', '').strip()
        if not title and request.is_json:
            title = request.json.get('title', '').strip()
            
        hackathon = Hackathon.query.get(hackathon_id)
        if hackathon and title:
            task = Task(hackathon_id=hackathon.id, title=title, completed=False)
            db.session.add(task)
            db.session.flush()
            progress = hackathon.update_progress()
            db.session.commit()
            
            if _is_ajax():
                completed_count = sum(1 for t in hackathon.tasks if t.completed)
                total_count = len(hackathon.tasks)
                return jsonify({
                    'success': True,
                    'task': {
                        'id': task.id,
                        'title': task.title,
                        'completed': task.completed
                    },
                    'hackathon_id': hackathon.id,
                    'progress': progress,
                    'completed_count': completed_count,
                    'total_count': total_count
                })
    except Exception as e:
        logger.error(f"Failed to add task for hackathon ID {hackathon_id}: {e}")
        db.session.rollback()
        if _is_ajax():
            return jsonify({'error': str(e)}), 500
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if not session.get('authenticated'):
        if _is_ajax():
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('hackathon.index'))
    
    try:
        task = Task.query.get(task_id)
        if not task:
            if _is_ajax():
                return jsonify({'error': 'Task not found'}), 404
            return redirect(url_for('hackathon.index', tab='tracker'))

        hackathon = task.hackathon
        db.session.delete(task)
        db.session.flush()
        progress = hackathon.update_progress()
        db.session.commit()
        
        if _is_ajax():
            completed_count = sum(1 for t in hackathon.tasks if t.completed)
            total_count = len(hackathon.tasks)
            return jsonify({
                'success': True,
                'task_id': task_id,
                'hackathon_id': hackathon.id,
                'progress': progress,
                'completed_count': completed_count,
                'total_count': total_count
            })
    except Exception as e:
        logger.error(f"Failed to delete task ID {task_id}: {e}")
        db.session.rollback()
        if _is_ajax():
            return jsonify({'error': str(e)}), 500
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/add_note/<int:hackathon_id>', methods=['POST'])
def add_note(hackathon_id):
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        note_text = request.form.get('note', '').strip()
        hackathon = Hackathon.query.get(hackathon_id)
        if hackathon and note_text:
            new_note = Note(
                hackathon_id=hackathon.id,
                progress=hackathon.progress,
                note=note_text
            )
            db.session.add(new_note)
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to add note for hackathon ID {hackathon_id}: {e}")
        db.session.rollback()
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/delete_hackathon/<int:hackathon_id>', methods=['POST'])
def delete_hackathon(hackathon_id):
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        hackathon = Hackathon.query.get(hackathon_id)
        if hackathon:
            for file_info in hackathon.file_attachments:
                delete_file_content(file_info.stored_filename)
            db.session.delete(hackathon)
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to delete hackathon ID {hackathon_id}: {e}")
        db.session.rollback()
        
    return redirect(url_for('hackathon.index', tab='tracker'))

@hackathon_bp.route('/move_to_participated/<int:hackathon_id>', methods=['POST'])
def move_to_participated(hackathon_id):
    """Move a hackathon from Progress Tracker to Participated Events."""
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        hackathon = Hackathon.query.get(hackathon_id)
        if not hackathon:
            logger.warning(f"Hackathon ID {hackathon_id} not found for move.")
            return redirect(url_for('hackathon.index', tab='tracker'))
        
        result = request.form.get('result', '').strip() or 'Completed'
        prize_won = request.form.get('prize_won', '').strip() or hackathon.prize_amount
        
        # Create participated event with all preserved metadata
        participated = ParticipatedEvent(
            name=hackathon.name,
            location=hackathon.location,
            event_type=hackathon.event_type,
            prize_amount=hackathon.prize_amount,
            date=hackathon.date,
            result_date=hackathon.result_date,
            url=hackathon.url,
            idea=hackathon.idea or hackathon.description,
            description=hackathon.idea or hackathon.description,
            result=result,
            prize_won=prize_won,
            is_idea_submission=hackathon.is_idea_submission,
            source_hackathon_id=hackathon.id
        )
        db.session.add(participated)
        db.session.flush()  # Get the participated.id
        
        # Re-associate notes
        for note in hackathon.notes:
            note.hackathon_id = None
            note.participated_event_id = participated.id
        
        # Move files and re-associate attachments
        for attachment in hackathon.file_attachments:
            move_file_to_participated_bucket(attachment.stored_filename)
            attachment.hackathon_id = None
            attachment.participated_event_id = participated.id
        
        # Delete the hackathon (notes/attachments are already moved)
        db.session.delete(hackathon)
        db.session.commit()
        
        logger.info(f"Moved hackathon '{hackathon.name}' (ID {hackathon_id}) to participated events.")
    except Exception as e:
        logger.error(f"Failed to move hackathon ID {hackathon_id} to participated: {e}")
        db.session.rollback()
    
    return redirect(url_for('hackathon.index', tab='participated'))

@hackathon_bp.route('/add_participated', methods=['POST'])
def add_participated():
    """Manually create a participated event."""
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        event_type = request.form.get('event_type', 'online').strip()
        prize_amount = request.form.get('prize_amount', '').strip()
        date = request.form.get('date', '').strip()
        result_date = request.form.get('result_date', '').strip()
        url = request.form.get('url', '').strip()
        idea = request.form.get('idea', '').strip()
        result = request.form.get('result', '').strip()
        
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        if name:
            event = ParticipatedEvent(
                name=name,
                location=location if location else None,
                event_type=event_type if event_type in ['online', 'offline'] else 'online',
                prize_amount=prize_amount if prize_amount else None,
                date=date if date else None,
                result_date=result_date if result_date else None,
                url=url if url else None,
                idea=idea if idea else None,
                description=idea if idea else None,
                result=result if result else 'Participated'
            )
            db.session.add(event)
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to add participated event: {e}")
        db.session.rollback()
    
    return redirect(url_for('hackathon.index', tab='participated'))

@hackathon_bp.route('/delete_participated/<int:event_id>', methods=['POST'])
def delete_participated(event_id):
    """Delete a participated event and its files."""
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        event = ParticipatedEvent.query.get(event_id)
        if event:
            for file_info in event.file_attachments:
                delete_file_content(file_info.stored_filename, bucket_type='participated')
            db.session.delete(event)
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to delete participated event ID {event_id}: {e}")
        db.session.rollback()
    
    return redirect(url_for('hackathon.index', tab='participated'))

@hackathon_bp.route('/export_csv')
def export_csv():
    if not session.get('authenticated'):
        return redirect(url_for('hackathon.index'))
    
    try:
        hackathons = Hackathon.query.all()
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Name', 'Type', 'Location', 'Prize', 'Date', 'Result Date', 'URL', 'Progress', 'Tasks', 'Notes'])
        
        for h in hackathons:
            tasks_str = '; '.join([f"[{'X' if t.completed else ' '}] {t.title}" for t in h.tasks])
            notes_str = '; '.join([f"{n.progress}%: {n.note}" for n in h.notes])
            writer.writerow([
                h.name or '',
                h.event_type or 'online',
                h.location or '',
                h.prize_amount or '',
                h.date or '',
                h.result_date or '',
                h.url or '',
                f"{h.progress}%",
                tasks_str,
                notes_str
            ])
            
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=hackathons.csv'}
        )
    except Exception as e:
        logger.error(f"Failed to export CSV: {e}")
        return redirect(url_for('hackathon.index'))
