from flask import Blueprint, render_template, request, session, jsonify
from bson import ObjectId
from app.db import get_db

wishlist_bp = Blueprint('wishlist', __name__, url_prefix='/wishlist')

_PLACEHOLDER_COLORS = [
    '#c4843c','#e8b8c0','#1e1e1e','#b8c8d8',
    '#e0d4b0','#b89060','#484038','#c8a870',
    '#c8c0a0','#d0a898','#d8d0b0','#9098a8',
]


@wishlist_bp.route('/')
def index():
    ids = session.get('wishlist', [])
    products = []

    if ids:
        db   = get_db()
        oids = []
        for pid in ids:
            try:
                oids.append(ObjectId(pid))
            except Exception:
                pass

        raw = list(db.products.find({'_id': {'$in': oids}, 'status': 'published'}))
        for i, p in enumerate(raw):
            p['_id'] = str(p['_id'])
            if not p.get('bg'):
                p['bg'] = _PLACEHOLDER_COLORS[i % len(_PLACEHOLDER_COLORS)]
        products = raw

    return render_template('wishlist.html', products=products)


@wishlist_bp.route('/toggle', methods=['POST'])
def toggle():
    data       = request.get_json(silent=True) or {}
    product_id = data.get('product_id') or request.form.get('product_id', '')

    if not product_id:
        return jsonify({'error': 'No product ID'}), 400

    wishlist = list(session.get('wishlist', []))

    if product_id in wishlist:
        wishlist.remove(product_id)
        wished = False
    else:
        wishlist.append(product_id)
        wished = True

    session['wishlist'] = wishlist
    session.modified    = True

    return jsonify({'wished': wished, 'count': len(wishlist)})
