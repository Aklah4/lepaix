import os
import uuid
from flask import Blueprint, render_template, redirect, request, url_for, flash, session, current_app

admin_settings_bp = Blueprint('admin_settings', __name__, url_prefix='/admin/settings')


def _auth_required():
    return session.get('admin_id') is None


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'webp', 'gif'}


@admin_settings_bp.route('/', methods=['GET', 'POST'])
def index():
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()
    settings = db.settings.find_one({'_id': 'site'}) or {}

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        if action == 'remove_banner':
            old = settings.get('banner_image')
            if old:
                try:
                    os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], old))
                except OSError:
                    pass
            db.settings.update_one(
                {'_id': 'site'},
                {'$unset': {'banner_image': ''}},
                upsert=True,
            )
            flash('Banner image removed.', 'success')
            return redirect(url_for('admin_settings.index'))

        file = request.files.get('banner_image')
        if file and file.filename and _allowed(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f'banner_{uuid.uuid4().hex}.{ext}'
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

            # Delete the old banner image if present
            old = settings.get('banner_image')
            if old:
                try:
                    os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], old))
                except OSError:
                    pass

            db.settings.update_one(
                {'_id': 'site'},
                {'$set': {'banner_image': filename}},
                upsert=True,
            )
            flash('Banner image updated.', 'success')
        else:
            flash('Please select a valid image file (PNG, JPG, WEBP, GIF).', 'error')

        return redirect(url_for('admin_settings.index'))

    return render_template('admin/settings.html', settings=settings)
