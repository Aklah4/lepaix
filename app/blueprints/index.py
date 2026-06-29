from flask import Blueprint, render_template
from app.db import get_db

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


@index_bp.route('/')
def index():
    db   = get_db()
    base = {'status': 'published', 'featured': True}

    women = _prep(list(db.products.find({**base, 'gender': 'Women'}).sort('created_at', -1).limit(8)))
    men   = _prep(list(db.products.find({**base, 'gender': 'Men'}).sort('created_at', -1).limit(8)), offset=8)

    settings = db.settings.find_one({'_id': 'site'}) or {}
    return render_template('index.html',
                           women_products=women,
                           men_products=men,
                           banner_image=settings.get('banner_image'))
