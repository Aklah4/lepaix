import re
from datetime import datetime, timezone
from bson import ObjectId
from flask import Blueprint, render_template, redirect, request, url_for, flash, session

admin_orders_bp = Blueprint('admin_orders', __name__, url_prefix='/admin/orders')

ORDER_STATUSES = ['pending', 'processing', 'shipped', 'delivered', 'cancelled']


def _auth_required():
    return session.get('admin_id') is None


@admin_orders_bp.route('/')
def index():
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    status_filter = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = 20

    query = {}
    if status_filter and status_filter in ORDER_STATUSES:
        query['status'] = status_filter
    if search:
        pattern = re.escape(search)
        query['$or'] = [
            {'order_number': {'$regex': pattern, '$options': 'i'}},
            {'customer.name': {'$regex': pattern, '$options': 'i'}},
            {'customer.email': {'$regex': pattern, '$options': 'i'}},
        ]

    total = db.orders.count_documents(query)
    orders = list(
        db.orders.find(query)
                 .sort('created_at', -1)
                 .skip((page - 1) * per_page)
                 .limit(per_page)
    )
    for o in orders:
        o['_id'] = str(o['_id'])

    total_pages = max(1, -(-total // per_page))

    counts = {s: db.orders.count_documents({'status': s}) for s in ORDER_STATUSES}
    counts['all'] = db.orders.count_documents({})

    return render_template(
        'admin/orders/index.html',
        orders=orders,
        status_filter=status_filter,
        search=search,
        page=page,
        total_pages=total_pages,
        total=total,
        counts=counts,
        ORDER_STATUSES=ORDER_STATUSES,
    )


@admin_orders_bp.route('/<order_id>')
def detail(order_id):
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    try:
        oid = ObjectId(order_id)
    except Exception:
        flash('Invalid order ID.', 'error')
        return redirect(url_for('admin_orders.index'))

    order = db.orders.find_one({'_id': oid})
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin_orders.index'))

    order['_id'] = str(order['_id'])
    return render_template(
        'admin/orders/detail.html',
        order=order,
        ORDER_STATUSES=ORDER_STATUSES,
    )


@admin_orders_bp.route('/<order_id>/status', methods=['POST'])
def update_status(order_id):
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    new_status = request.form.get('status', '').strip()
    if new_status not in ORDER_STATUSES:
        flash('Invalid status.', 'error')
        return redirect(url_for('admin_orders.detail', order_id=order_id))

    try:
        oid = ObjectId(order_id)
    except Exception:
        flash('Invalid order ID.', 'error')
        return redirect(url_for('admin_orders.index'))

    db.orders.update_one(
        {'_id': oid},
        {'$set': {'status': new_status, 'updated_at': datetime.now(timezone.utc)}},
    )
    flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('admin_orders.detail', order_id=order_id))
