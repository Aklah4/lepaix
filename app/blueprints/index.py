import re

from flask import Blueprint, render_template, request
from app.db import get_db
from app.blueprints.admin.categories import ensure_default_categories
from app.extensions import limiter

index_bp = Blueprint('index', __name__)

_PLACEHOLDER_COLORS = [
    '#c4843c','#e8b8c0','#1e1e1e','#b8c8d8',
    '#e0d4b0','#b89060','#484038','#c8a870',
    '#c8c0a0','#d0a898','#d8d0b0','#9098a8',
]


def _prep(products, offset=0):
    for i, p in enumerate(products):
        p['_id'] = str(p['_id'])
        if not p.get('bg'):
            p['bg'] = _PLACEHOLDER_COLORS[(i + offset) % len(_PLACEHOLDER_COLORS)]
    return products


@index_bp.route('/search')
@limiter.limit('30 per minute')
def search():
    db = get_db()
    q  = request.args.get('q', '').strip()[:100]
    products = []
    if q:
        pattern = re.escape(q)
        raw = list(db.products.find({
            'status': 'published',
            '$or': [
                {'name':        {'$regex': pattern, '$options': 'i'}},
                {'category':    {'$regex': pattern, '$options': 'i'}},
                {'description': {'$regex': pattern, '$options': 'i'}},
            ]
        }).sort('created_at', -1))
        products = _prep(raw)
    return render_template('search.html', products=products, q=q)


@index_bp.route('/')
def index():
    db = get_db()

    ensure_default_categories(db)
    categories = list(db.categories.find().sort('order', 1))
    for c in categories:
        c['_id'] = str(c['_id'])

    settings = db.settings.find_one({'_id': 'site'}) or {}
    return render_template('index.html',
                           categories=categories,
                           banner_image=settings.get('banner_image'))
