from flask import Blueprint, render_template, abort, request
from bson import ObjectId
from app.db import get_db
from app.sizes import size_options

products_bp = Blueprint('products', __name__, url_prefix='/products')

PER_PAGE = 24

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


def _page_numbers(page, total_pages, edge=1, around=1):
    """Page links to render: first/last pages, a window around the current one,
    and None wherever a run of pages was skipped (rendered as an ellipsis)."""
    keep = {p for p in range(1, edge + 1)}
    keep |= {p for p in range(total_pages - edge + 1, total_pages + 1)}
    keep |= {p for p in range(page - around, page + around + 1)}
    keep = sorted(p for p in keep if 1 <= p <= total_pages)

    out, prev = [], 0
    for p in keep:
        if prev and p - prev > 1:
            out.append(None)
        out.append(p)
        prev = p
    return out


@products_bp.route('/')
def index():
    db       = get_db()
    gender   = request.args.get('gender', '')
    category = request.args.get('category', '')

    query = {'status': 'published'}
    if gender in ('Women', 'Men'):
        query['gender'] = gender

    cat_query  = {**query}
    categories = ['All'] + sorted(c for c in db.products.distinct('category', cat_query) if c)

    if category and category != 'All':
        query['category'] = category

    total       = db.products.count_documents(query)
    total_pages = max(1, -(-total // PER_PAGE))

    try:
        page = int(request.args.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    raw = list(db.products.find(query)
               .sort('created_at', -1)
               .skip((page - 1) * PER_PAGE)
               .limit(PER_PAGE))
    products = _prep(raw)

    return render_template('products/index.html', products=products,
                           categories=categories, active_gender=gender,
                           active_category=category,
                           page=page, total_pages=total_pages, total=total,
                           page_numbers=_page_numbers(page, total_pages))


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

    return render_template('products/detail.html', product=product, related=related,
                           default_sizes=size_options(product.get('category')))
