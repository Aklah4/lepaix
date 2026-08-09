"""Stock helpers.

A product's `stock` is the number of units on hand. Zero means sold out, and
everything - the badge on a card, the Add to cart button, the guard in the
cart, the check at order creation - goes through here so the storefront and
the server can never disagree about what is available.

A product with no `stock` field at all is treated as available. The field has
been written by the product form for a long time, so a missing one means an
old document rather than an empty shelf, and hiding sellable stock is the
worse mistake of the two.
"""

UNLIMITED = None


def stock_level(product):
    """Units on hand, or None when the product doesn't track stock."""
    if not product:
        return 0
    if 'stock' not in product or product.get('stock') is None:
        return UNLIMITED
    try:
        return max(0, int(product['stock']))
    except (TypeError, ValueError):
        # A non-numeric stock value is a data problem, not a sold-out product.
        return UNLIMITED


def is_out_of_stock(product):
    """True only when we positively know there is none left."""
    return stock_level(product) == 0


def in_stock(product):
    return not is_out_of_stock(product)


def is_low_stock(product, threshold=5):
    """Few enough left to be worth telling the shopper about."""
    level = stock_level(product)
    return level is not None and 0 < level <= threshold


def available_quantity(product, requested):
    """How many of `requested` can actually be sold. Never more than on hand."""
    try:
        requested = max(0, int(requested))
    except (TypeError, ValueError):
        requested = 0
    level = stock_level(product)
    if level is UNLIMITED:
        return requested
    return min(requested, level)


# ── Moving stock when an order's status changes ──────────────────────────────
#
# Stock is held by an order only once it is confirmed - see
# STOCK_HOLDING_STATUSES in the orders blueprint. A pending order (placed but
# not yet paid for) does not reserve anything, so an abandoned checkout never
# sits on stock somebody else could have bought.

def _order_lines(order):
    """(ObjectId, quantity) for each line of an order that has both."""
    from bson import ObjectId

    for line in order.get('items', []):
        try:
            oid = ObjectId(line.get('product_id'))
            quantity = int(line.get('quantity') or 0)
        except Exception:
            continue
        if quantity > 0:
            yield oid, quantity, line.get('product_name', '')


def deduct_for_order(db, order):
    """Take this order's items off the shelf. Returns lines that came up short.

    The decrement is conditional on there being enough on hand, so two orders
    confirmed at the same moment cannot drive a product negative. A line that
    cannot be covered sets that product to zero and is reported back, because
    it means the shop has just promised something it does not have.
    """
    short = []

    for oid, quantity, name in _order_lines(order):
        product = db.products.find_one({'_id': oid}, {'stock': 1, 'name': 1})
        if not product or stock_level(product) is UNLIMITED:
            continue  # this product does not track stock

        result = db.products.update_one(
            {'_id': oid, 'stock': {'$gte': quantity}},
            {'$inc': {'stock': -quantity}},
        )
        if not result.matched_count:
            # Not enough left. Floor at zero rather than going negative.
            db.products.update_one({'_id': oid}, {'$set': {'stock': 0}})
            short.append(name or product.get('name', ''))

    return short


def restore_for_order(db, order):
    """Put this order's items back - a cancellation, or a reversion to pending."""
    for oid, quantity, _name in _order_lines(order):
        product = db.products.find_one({'_id': oid}, {'stock': 1})
        if not product or stock_level(product) is UNLIMITED:
            continue
        db.products.update_one({'_id': oid}, {'$inc': {'stock': quantity}})
