from flask import Blueprint, render_template, abort, request
from bson import ObjectId
from app.db import get_db

products_bp = Blueprint('products', __name__, url_prefix='/products')

_PLACEHOLDER_COLORS = [
    '#c4843c','#e8b8c0','#1e1e1e','#b8c8d8',
    '#e0d4b0','#b89060','#484038','#c8a870',
    '#c8c0a0','#d0a898','#d8d0b0','#9098a8',
]


def _prep(products):
    """Stringify _id and attach a placeholder bg for cards without images."""
    for i, p in enumerate(products):
        p['_id'] = str(p['_id'])
        if not p.get('bg'):
            p['bg'] = _PLACEHOLDER_COLORS[i % len(_PLACEHOLDER_COLORS)]
    return products


@products_bp.route('/')
def index():
    db     = get_db()
    gender = request.args.get('gender', '')

    query = {'status': 'published'}
    if gender in ('Women', 'Men'):
        query['gender'] = gender

    cat_query  = {**query}
    categories = ['All'] + db.products.distinct('category', cat_query)
    raw        = list(db.products.find(query).sort('created_at', -1).limit(24))
    products   = _prep(raw)

    return render_template('products/index.html', products=products,
                           categories=categories, active_gender=gender)


@products_bp.route('/<product_id>')
def detail(product_id):
    db = get_db()
    try:
        product = db.products.find_one({'_id': ObjectId(product_id)})
    except Exception:
        abort(404)

    if not product:
        abort(404)

    product['_id'] = str(product['_id'])
    if not product.get('bg'):
        product['bg'] = _PLACEHOLDER_COLORS[0]

    related = list(db.products.find({
        'category': product.get('category'),
        'status':   'published',
        '_id':      {'$ne': ObjectId(product_id)},
    }).limit(4))
    _prep(related)

    return render_template('products/detail.html', product=product, related=related)
