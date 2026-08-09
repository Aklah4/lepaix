"""Delivery fee calculation.

One entry point:

    from app.delivery import quote_delivery
    quote = quote_delivery(cart, address, strict=True)

`cart` is the enriched cart lines the cart and checkout blueprints already
build - each a mapping with `quantity`, a unit `price`, and ideally the
`product` document it came from (that is where weight and shipping class are
read from). `address` is a mapping with any of `zone_id`, `state`, `city`,
`lga`; anything else on it is ignored.

The module computes and returns. It does not persist the quote, email it,
refund it, or know that orders exist - the checkout blueprint snapshots the
quote onto the order, because that is the checkout's job.

Rates are configured in the admin panel (Admin → Delivery), which is the only
other thing that reaches into this package, through `repository`.
"""

from app.delivery.service import quote_delivery
from app.delivery.types import (REASON_NO_ADDRESS, REASON_STRATEGY_UNAVAILABLE,
                                REASON_UNRESOLVED_ZONE, DeliveryQuote,
                                LineAdjustment, QuoteContext)

__all__ = [
    'quote_delivery',
    'DeliveryQuote', 'LineAdjustment', 'QuoteContext',
    # The vocabulary of DeliveryQuote.reason - part of the public contract,
    # since a caller has to tell a shopper which of these happened.
    'REASON_NO_ADDRESS', 'REASON_UNRESOLVED_ZONE', 'REASON_STRATEGY_UNAVAILABLE',
]
