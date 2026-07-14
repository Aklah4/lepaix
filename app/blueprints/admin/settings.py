from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from app.uploader import delete_image, upload_image

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
            delete_image(old)
            db.settings.update_one(
                {'_id': 'site'},
                {'$unset': {'banner_image': ''}},
                upsert=True,
            )
            flash('Banner image removed.', 'success')
            return redirect(url_for('admin_settings.index'))

        if action == 'save_rate':
            rate_s = request.form.get('ngn_per_usd', '').strip()
            try:
                rate = float(rate_s)
                if rate <= 0:
                    raise ValueError
            except ValueError:
                flash('Exchange rate must be a positive number.', 'error')
                return redirect(url_for('admin_settings.index'))

            db.settings.update_one(
                {'_id': 'site'},
                {'$set': {'ngn_per_usd': rate}},
                upsert=True,
            )
            flash('Exchange rate updated.', 'success')
            return redirect(url_for('admin_settings.index'))

        if action == 'remove_logo':
            delete_image(settings.get('site_logo'))
            db.settings.update_one(
                {'_id': 'site'},
                {'$unset': {'site_logo': ''}},
                upsert=True,
            )
            flash('Site logo removed.', 'success')
            return redirect(url_for('admin_settings.index'))

        if action == 'save_logo':
            file = request.files.get('site_logo')
            if file and file.filename and _allowed(file.filename):
                delete_image(settings.get('site_logo'))
                url = upload_image(file, folder='lepaix/settings')
                db.settings.update_one(
                    {'_id': 'site'},
                    {'$set': {'site_logo': url}},
                    upsert=True,
                )
                flash('Site logo updated.', 'success')
            else:
                flash('Please select a valid image file (PNG, JPG, WEBP, GIF).', 'error')
            return redirect(url_for('admin_settings.index'))

        file = request.files.get('banner_image')
        if file and file.filename and _allowed(file.filename):
            delete_image(settings.get('banner_image'))
            url = upload_image(file, folder='lepaix/settings')
            db.settings.update_one(
                {'_id': 'site'},
                {'$set': {'banner_image': url}},
                upsert=True,
            )
            flash('Banner image updated.', 'success')
        else:
            flash('Please select a valid image file (PNG, JPG, WEBP, GIF).', 'error')

        return redirect(url_for('admin_settings.index'))

    return render_template('admin/settings.html', settings=settings)
