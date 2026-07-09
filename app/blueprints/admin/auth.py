from bson import ObjectId
from flask import Blueprint, redirect, request, jsonify, session, url_for, render_template
import bcrypt
from app.db import get_db
from app.extensions import limiter


admin_auth_bp = Blueprint('admin_auth', __name__, url_prefix='/admin/auth')

# Compared against when the username doesn't exist, so a login attempt takes the
# same time either way and can't be used to enumerate valid usernames by timing.
_DUMMY_HASH = bcrypt.hashpw(b'no-such-user', bcrypt.gensalt()).decode('utf-8')


@admin_auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if request.method == 'GET':
        if session.get('admin_id'):
            return redirect(url_for('admin.dashboard'))
        return render_template('admin/login.html', error=None)

    # POST - process form
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    admin = get_db().admins.find_one({'username': username})
    stored = admin.get('password', '') if admin else _DUMMY_HASH
    try:
        checkpw_ok = bcrypt.checkpw(password.encode('utf-8'), stored.encode('utf-8'))
    except Exception:
        checkpw_ok = False

    valid = bool(admin) and checkpw_ok

    if valid:
        session['admin_id'] = str(admin['_id'])
        session['admin_username'] = admin['username']
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/login.html', error='Invalid username or password'), 401


@admin_auth_bp.route('/logout')
def logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_auth.login'))


@admin_auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))

    if request.method == 'GET':
        return render_template('admin/reset_password.html', error=None, success=None)

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not current_password or not new_password or not confirm_password:
        return render_template('admin/reset_password.html', error='All fields are required.', success=None), 400

    if new_password != confirm_password:
        return render_template('admin/reset_password.html', error='New passwords do not match.', success=None), 400

    try:
        admin_id = ObjectId(session['admin_id'])
    except Exception:
        return redirect(url_for('admin_auth.login'))

    admin = get_db().admins.find_one({'_id': admin_id})
    if not admin:
        return redirect(url_for('admin_auth.login'))

    stored = admin.get('password', '')
    try:
        valid_current = bcrypt.checkpw(current_password.encode('utf-8'), stored.encode('utf-8'))
    except Exception:
        valid_current = False

    if not valid_current:
        return render_template('admin/reset_password.html', error='Current password is incorrect.', success=None), 401

    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    get_db().admins.update_one({'_id': admin['_id']}, {'$set': {'password': hashed}})

    return render_template('admin/reset_password.html', error=None, success='Password updated successfully.')


# Admin dashboard blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
def dashboard():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    total_products     = db.products.count_documents({})
    published_products = db.products.count_documents({'status': 'published'})
    draft_products     = db.products.count_documents({'status': 'draft'})

    # Orders
    total_orders   = db.orders.count_documents({})
    pending_orders = db.orders.count_documents({'status': 'pending'})
    revenue_agg = list(db.orders.aggregate([
        {'$match': {'status': {'$nin': ['cancelled']}}},
        {'$group': {'_id': None, 'total': {'$sum': '$total'}}},
    ]))
    total_revenue = revenue_agg[0]['total'] if revenue_agg else 0.0

    # Low-stock products
    low_stock = list(
        db.products.find({'stock': {'$gt': 0, '$lt': 10}})
                   .sort('stock', 1)
                   .limit(5)
    )
    for p in low_stock:
        p['_id'] = str(p['_id'])

    # Recent orders
    recent_orders = list(
        db.orders.find()
                 .sort('created_at', -1)
                 .limit(5)
    )
    for o in recent_orders:
        o['_id'] = str(o['_id'])

    return render_template(
        'admin/dashboard.html',
        admin_username=session.get('admin_username', 'Admin'),
        total_products=total_products,
        published_products=published_products,
        draft_products=draft_products,
        total_orders=total_orders,
        pending_orders=pending_orders,
        total_revenue=total_revenue,
        low_stock=low_stock,
        recent_orders=recent_orders,
    )

