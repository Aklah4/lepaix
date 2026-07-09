from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from bson import ObjectId
from app.extensions import limiter

checkout_bp = Blueprint('checkout', __name__, url_prefix='/checkout')


def _next_order_number(db):
    counter = db.counters.find_one_and_update(
        {'_id': 'order_number'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=True,
    )
    seq = counter.get('seq', 1)
    return f'LP-{seq:05d}'


@checkout_bp.route('/', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def index():
    from app.db import get_db
    db = get_db()

    cart = session.get('cart', [])
    if not cart:
        flash('Your cart is empty.', 'error')
        return redirect(url_for('cart.index'))

    # Enrich cart items with product data
    enriched = []
    for item in cart:
        try:
            product = db.products.find_one({'_id': ObjectId(item['product_id'])})
        except Exception:
            product = None
        if product:
            enriched.append({
                'product_id': item['product_id'],
                'product_name': product['name'],
                'price': product['price'],
                'size': item.get('size', ''),
                'color': item.get('color', ''),
                'quantity': item['quantity'],
                'image': product.get('images', [None])[0],
                'subtotal': product['price'] * item['quantity'],
            })

    if not enriched:
        flash('Some cart items are no longer available.', 'error')
        return redirect(url_for('cart.index'))

    subtotal = sum(i['subtotal'] for i in enriched)
    shipping = 0.00
    total = subtotal + shipping

    if request.method == 'GET':
        return render_template('checkout/index.html',
                               cart=enriched, subtotal=subtotal,
                               shipping=shipping, total=total)

    # POST — place order
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    city = request.form.get('city', '').strip()
    country = request.form.get('country', '').strip()
    notes = request.form.get('notes', '').strip()

    if not name or not email or not address or not city or not country:
        flash('Please fill in all required fields.', 'error')
        return render_template('checkout/index.html',
                               cart=enriched, subtotal=subtotal,
                               shipping=shipping, total=total,
                               form=request.form)

    order_doc = {
        'order_number': _next_order_number(db),
        'customer': {
            'name': name,
            'email': email,
            'phone': phone,
            'address': address,
            'city': city,
            'country': country,
        },
        'items': enriched,
        'subtotal': round(subtotal, 2),
        'shipping_cost': round(shipping, 2),
        'total': round(total, 2),
        'status': 'pending',
        'notes': notes,
        'created_at': datetime.now(timezone.utc),
        'updated_at': datetime.now(timezone.utc),
    }

    result = db.orders.insert_one(order_doc)
    order_id = str(result.inserted_id)
    order_number = order_doc['order_number']

    session['cart'] = []
    session.modified = True

    return redirect(url_for('checkout.confirmation',
                            order_id=order_id, order_number=order_number))


@checkout_bp.route('/confirmation')
def confirmation():
    order_id = request.args.get('order_id', '')
    order_number = request.args.get('order_number', '')
    return render_template('checkout/confirmation.html',
                           order_id=order_id, order_number=order_number)
