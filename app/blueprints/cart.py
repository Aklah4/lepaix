from flask import Blueprint, session, redirect, request, url_for, render_template, flash
from bson import ObjectId

cart_bp = Blueprint('cart', __name__, url_prefix='/cart')


def get_cart():
    return session.setdefault('cart', [])


def _save_cart(cart):
    session['cart'] = cart
    session.modified = True


@cart_bp.route('/')
def index():
    from app.db import get_db
    db = get_db()
    cart = get_cart()

    enriched = []
    for item in cart:
        try:
            product = db.products.find_one({'_id': ObjectId(item['product_id'])})
        except Exception:
            product = None

        if product:
            enriched.append({
                'product_id': item['product_id'],
                'name': product['name'],
                'price': product['price'],
                'size': item.get('size', ''),
                'color': item.get('color', ''),
                'quantity': item['quantity'],
                'image': product.get('images', [None])[0],
                'subtotal': product['price'] * item['quantity'],
            })

    cart_total = sum(i['subtotal'] for i in enriched)
    return render_template('cart/index.html', cart=enriched, cart_total=cart_total)


@cart_bp.route('/add', methods=['POST'])
def add():
    product_id = request.form.get('product_id', '').strip()
    size = request.form.get('size', '').strip()
    color = request.form.get('color', '').strip()
    try:
        quantity = max(1, int(request.form.get('quantity', 1)))
    except ValueError:
        quantity = 1

    if not product_id:
        flash('Product not found.', 'error')
        return redirect(request.referrer or url_for('products.index'))

    cart = get_cart()
    for item in cart:
        if item['product_id'] == product_id and item.get('size') == size and item.get('color') == color:
            item['quantity'] += quantity
            _save_cart(cart)
            flash('Cart updated.', 'success')
            return redirect(request.referrer or url_for('products.index'))

    cart.append({'product_id': product_id, 'size': size, 'color': color, 'quantity': quantity})
    _save_cart(cart)
    flash('Item added to cart.', 'success')
    return redirect(request.referrer or url_for('products.index'))


@cart_bp.route('/remove', methods=['POST'])
def remove():
    product_id = request.form.get('product_id', '').strip()
    size = request.form.get('size', '').strip()
    color = request.form.get('color', '').strip()

    cart = get_cart()
    cart = [
        i for i in cart
        if not (i['product_id'] == product_id and i.get('size') == size and i.get('color') == color)
    ]
    _save_cart(cart)
    flash('Item removed.', 'success')
    return redirect(url_for('cart.index'))


@cart_bp.route('/update', methods=['POST'])
def update():
    product_id = request.form.get('product_id', '').strip()
    size = request.form.get('size', '').strip()
    color = request.form.get('color', '').strip()
    try:
        quantity = max(0, int(request.form.get('quantity', 1)))
    except ValueError:
        quantity = 1

    cart = get_cart()
    if quantity == 0:
        cart = [
            i for i in cart
            if not (i['product_id'] == product_id and i.get('size') == size and i.get('color') == color)
        ]
    else:
        for item in cart:
            if item['product_id'] == product_id and item.get('size') == size and item.get('color') == color:
                item['quantity'] = quantity
                break
    _save_cart(cart)
    return redirect(url_for('cart.index'))
