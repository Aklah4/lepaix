import re

from flask import Blueprint, render_template, request, session, redirect, url_for

from app.db import get_db


admin_customers_bp = Blueprint(
    'admin_customers', __name__, url_prefix='/admin/customers'
)


@admin_customers_bp.route('/')
def index():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))

    page = max(1, request.args.get('page', 1, type=int))
    per_page = 25
    search = request.args.get('q', '').strip()
    pipeline = [{'$match': {'customer.email': {'$exists': True, '$ne': ''}}}]
    if search:
        term = re.escape(search)
        pipeline.append({'$match': {'$or': [
            {'customer.name': {'$regex': term, '$options': 'i'}},
            {'customer.email': {'$regex': term, '$options': 'i'}},
            {'customer.phone': {'$regex': term, '$options': 'i'}},
        ]}})

    pipeline.extend([
        {'$sort': {'created_at': -1}},
        {'$group': {
            '_id': {'$toLower': {'$ifNull': ['$customer.email', ''] }},
            'customer': {'$first': '$customer'},
            'order_count': {'$sum': 1},
            'last_order': {'$max': '$created_at'},
        }},
        {'$sort': {'last_order': -1, '_id': 1}},
        {'$facet': {
            'customers': [
                {'$skip': (page - 1) * per_page},
                {'$limit': per_page},
            ],
            'total': [{'$count': 'count'}],
        }},
    ])

    result = next(iter(get_db().orders.aggregate(pipeline)), {})
    customers = result.get('customers', [])
    total_rows = result.get('total', [])
    total = total_rows[0]['count'] if total_rows else 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        'admin/customers/index.html',
        customers=customers,
        search=search,
        page=page,
        total=total,
        total_pages=total_pages,
    )
