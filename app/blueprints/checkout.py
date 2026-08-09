from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from bson import ObjectId
from app.delivery import (REASON_NO_ADDRESS, REASON_STRATEGY_UNAVAILABLE,
                          REASON_UNRESOLVED_ZONE, quote_delivery)
from app.delivery.repository import ZoneRepository
from app.emails import send_order_emails
from app.extensions import limiter
from app.pricing import effective_price, is_on_sale

checkout_bp = Blueprint('checkout', __name__, url_prefix='/checkout')

# What the shopper reads when we could not price their delivery. The delivery
# module returns a code; the wording is this blueprint's business.
DELIVERY_MESSAGES = {
    REASON_NO_ADDRESS:
        'Choose your delivery area so we can work out the delivery fee.',
    REASON_UNRESOLVED_ZONE:
        "We don't have a delivery rate for that address yet. Pick the closest "
        'delivery area from the list, or message us on WhatsApp and we will sort it out.',
    REASON_STRATEGY_UNAVAILABLE:
        "We couldn't work out a delivery fee just now. Please try again in a moment.",
}
DELIVERY_FALLBACK_MESSAGE = DELIVERY_MESSAGES[REASON_UNRESOLVED_ZONE]


def _next_order_number(db):
    counter = db.counters.find_one_and_update(
        {'_id': 'order_number'},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=True,
    )
    seq = counter.get('seq', 1)
    return f'LP-{seq:05d}'


def _address_for_quote(zone_id, state='', city=''):
    """The address the quote is made against, or None if we were told nothing.

    Passing an empty address through as a dict would come back "no rate for
    that address" when the truth is the shopper simply hasn't picked an area
    yet - two different messages.
    """
    if not (zone_id or state or city):
        return None
    return {'zone_id': zone_id or None, 'state': state, 'city': city}


def _delivery_snapshot(quote):
    """Freeze the quote onto the order.

    Amounts go in as strings, exactly as quoted. A rate change next month must
    not rewrite what this customer was charged, and a string cannot be
    re-interpreted by a later float conversion the way a number can.
    """
    return {
        'amount': str(quote.amount),
        'currency': quote.currency,
        'zone_id': quote.zone_id,
        'billable_weight_g': quote.billable_weight_g,
        'breakdown': [
            {'label': line.label, 'amount': str(line.amount), 'code': line.code}
            for line in quote.breakdown
        ],
        'quoted_at': datetime.now(timezone.utc),
    }


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
            unit_price = effective_price(product)
            enriched.append({
                'product_id': item['product_id'],
                'product_name': product['name'],
                'price': unit_price,
                'size': item.get('size', ''),
                'color': item.get('color', ''),
                'quantity': item['quantity'],
                'image': product.get('images', [None])[0],
                'subtotal': unit_price * item['quantity'],
                # Record the markdown so the order shows what was saved.
                'original_price': product['price'] if is_on_sale(product) else None,
                # What the delivery quote prices from, kept on the line so the
                # order records the weight it was actually charged for.
                'weight_grams': product.get('weight_grams'),
                'shipping_class': product.get('shipping_class'),
            })

    if not enriched:
        flash('Some cart items are no longer available.', 'error')
        return redirect(url_for('cart.index'))

    subtotal = sum(i['subtotal'] for i in enriched)
    zones = ZoneRepository(db).active_zones()

    if request.method == 'GET':
        # An estimate from whatever the shopper already told the cart page.
        quote = quote_delivery(
            enriched, _address_for_quote(session.get('delivery_zone_id')))
        shipping = float(quote.amount) if quote.resolved else 0.0
        return render_template('checkout/index.html',
                               cart=enriched, subtotal=subtotal,
                               shipping=shipping, total=subtotal + shipping,
                               quote=quote, zones=zones,
                               form={'zone_id': session.get('delivery_zone_id') or ''})

    # POST — place order
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    address_line = request.form.get('address', '').strip()
    city = request.form.get('city', '').strip()
    state = request.form.get('state', '').strip()
    country = request.form.get('country', '').strip()
    zone_id = request.form.get('zone_id', '').strip()
    notes = request.form.get('notes', '').strip()

    # The fee is never read from the form. It is recalculated here, from the
    # rate tables as they stand right now, whatever the page was showing.
    quote = quote_delivery(
        enriched, _address_for_quote(zone_id, state, city), strict=True)
    shipping = float(quote.amount)
    total = subtotal + shipping

    def _reshow(message):
        flash(message, 'error')
        return render_template('checkout/index.html',
                               cart=enriched, subtotal=subtotal,
                               shipping=shipping if quote.resolved else 0.0,
                               total=subtotal + (shipping if quote.resolved else 0.0),
                               quote=quote, zones=zones, form=request.form)

    if not name or not email or not address_line or not city or not country:
        return _reshow('Please fill in all required fields.')

    if not quote.resolved:
        # No delivery rate, no order. Guessing a fee here is how a shop
        # discovers at month end that it has been paying to ship.
        return _reshow(DELIVERY_MESSAGES.get(quote.reason, DELIVERY_FALLBACK_MESSAGE))

    order_doc = {
        'order_number': _next_order_number(db),
        'customer': {
            'name': name,
            'email': email,
            'phone': phone,
            'address': address_line,
            'city': city,
            'state': state,
            'country': country,
        },
        'items': enriched,
        'subtotal': round(subtotal, 2),
        # Kept as a float, and kept in step with delivery.amount below: the
        # order templates and the emails have always read this field.
        'shipping_cost': round(shipping, 2),
        'total': round(total, 2),
        # The authoritative record of what was charged and why.
        'delivery': _delivery_snapshot(quote),
        'status': 'pending',
        'notes': notes,
        'created_at': datetime.now(timezone.utc),
        'updated_at': datetime.now(timezone.utc),
    }

    result = db.orders.insert_one(order_doc)
    order_id = str(result.inserted_id)
    order_number = order_doc['order_number']

    # Confirmation to the customer + notification to the vendor. Never raises.
    send_order_emails(order_doc)

    session['cart'] = []
    session.pop('delivery_zone_id', None)
    session.modified = True

    return redirect(url_for('checkout.payment',
                            order_id=order_id, order_number=order_number))


@checkout_bp.route('/payment')
def payment():
    from app.db import get_db
    db = get_db()

    order_id = request.args.get('order_id', '')
    order_number = request.args.get('order_number', '')

    total = None
    try:
        order = db.orders.find_one({'_id': ObjectId(order_id)})
    except Exception:
        order = None
    if order:
        total = order.get('total')

    return render_template('checkout/payment.html',
                           order_id=order_id, order_number=order_number,
                           total=total)


@checkout_bp.route('/confirmation')
def confirmation():
    order_id = request.args.get('order_id', '')
    order_number = request.args.get('order_number', '')
    return render_template('checkout/confirmation.html',
                           order_id=order_id, order_number=order_number)
