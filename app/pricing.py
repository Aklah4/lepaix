"""Sale-price helpers.

A product's `price` is always its regular price. `sale_price` is optional; a
product is "on sale" only when `sale_price` is a positive number strictly below
`price`. Everything - storefront display and the amount actually charged at
checkout - goes through here so the two can never disagree.
"""


def _num(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def is_on_sale(product):
    """True when the product has a valid sale price below its regular price."""
    if not product:
        return False
    regular = _num(product.get('price'))
    sale = _num(product.get('sale_price'))
    return bool(regular and sale and sale < regular)


def effective_price(product):
    """The price a customer actually pays - sale price when on sale, else price."""
    if is_on_sale(product):
        return float(product['sale_price'])
    return float(_num(product.get('price')) or 0)


def discount_percent(product):
    """Whole-number percent off, e.g. 25 for a 25% markdown. 0 when not on sale."""
    if not is_on_sale(product):
        return 0
    regular = float(product['price'])
    sale = float(product['sale_price'])
    return int(round((regular - sale) / regular * 100))
