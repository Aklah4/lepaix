"""`quote_delivery` - the only thing outside this module ever calls.

THE CALCULATION ORDER BELOW IS LOAD-BEARING. Steps 1-9 run in exactly this
sequence, and the sequence is the business rule:

    1. Partition the cart into shippable and non-shippable lines.
    2. Short-circuit: nothing shippable means no delivery and no fee.
    3. Resolve the destination address to a zone.
    4. Billable weight, over shippable lines only.
    5. Base fee.                    ┐
    6. Weight adjustment.           │ the rules pipeline, in list order
    7. Surcharges.                  │
    8. Discounts.                   ┘
    9. Clamp at zero, round to the configured unit.

Surcharges (7) resolve BEFORE discounts (8), so a percentage discount applies
to the surcharged total. This is a deliberate business decision, not an
accident of ordering: the alternative discounts the base fee and then adds a
fragile-item surcharge on top, which reads to the customer as a discount that
did not apply. Step 7 has no rules in it yet - see rules.py.
"""

import logging
import time
from dataclasses import replace
from decimal import Decimal

from app.delivery import repository
from app.delivery.cache import quote_cache
from app.delivery.money import ZERO, to_decimal
from app.delivery.resolver import resolve_zone
from app.delivery.strategies import STRATEGIES, FlatRateStrategy, unresolved
from app.delivery.types import (NON_SHIPPABLE_CLASSES, REASON_NO_ADDRESS,
                                REASON_STRATEGY_UNAVAILABLE, SHIPPABLE,
                                REASON_UNRESOLVED_ZONE, CartLine, DeliveryQuote,
                                QuoteContext)

log = logging.getLogger(__name__)


def quote_delivery(cart, address, *, strict: bool = False) -> DeliveryQuote:
    """Price the delivery for `cart` to `address`.

    strict=False - the cart-page estimate. A missing or unresolvable address
    is fine; the quote comes back `resolved=False` with a reason instead of
    raising, and the page says so.

    strict=True - checkout and order creation. An unresolvable address still
    comes back `resolved=False`, and the caller MUST block the order. Neither
    mode ever guesses a fee.
    """
    repo = repository.default_repository()
    settings = repo.settings()
    currency = settings['currency']

    # ── 1. Partition ────────────────────────────────────────────────────────
    shippable, _non_shippable = _partition(cart, settings)

    # ── 2. Short-circuit ────────────────────────────────────────────────────
    if not shippable:
        return DeliveryQuote(
            amount=ZERO, currency=currency, zone_id=None, breakdown=[],
            billable_weight_g=0, resolved=True, reason=None)

    # ── 3. Resolve destination ──────────────────────────────────────────────
    zone = resolve_zone(address, repo, use_cache=not strict) if address else None

    # ── 4. Billable weight ──────────────────────────────────────────────────
    billable_weight_g = _billable_weight(shippable, settings)

    ctx = _build_context(shippable, zone, billable_weight_g, settings, strict)

    # A strict quote never reads the cache: order creation recalculates from
    # the live rate tables, so an admin's price change can't be served stale
    # to the one request where the money actually moves.
    cache_key = None
    if not strict:
        cache_key = _cache_key(ctx, settings)
        cached = quote_cache.get(cache_key)
        if cached is not None:
            return cached

    # ── 5-9. Price it ───────────────────────────────────────────────────────
    quote = _run_strategy(ctx, settings)

    if not quote.resolved and quote.reason == REASON_UNRESOLVED_ZONE and not address:
        # More precise than "we have no rate for there": there was no there.
        quote = replace(quote, reason=REASON_NO_ADDRESS)

    if not quote.resolved and strict:
        log.info('Delivery unresolved at checkout (%s): zone=%s weight=%sg',
                 quote.reason, ctx.zone_id, billable_weight_g)

    if cache_key is not None and quote.resolved:
        quote_cache.set(cache_key, quote)

    return quote


# ── Step 1: partition ────────────────────────────────────────────────────────
def _partition(cart, settings):
    """Split the cart into (shippable, non_shippable) CartLines.

    Accepts the enriched cart dicts the cart and checkout blueprints already
    build. A line's price is always recomputed here from the unit price and
    quantity - a posted `subtotal` is never trusted, on the same principle
    that a posted delivery fee is never trusted.
    """
    shippable, non_shippable = [], []
    default_weight = settings['default_item_weight_g']

    for item in cart or []:
        product = item.get('product') or {}

        try:
            quantity = int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            continue

        unit_price = _unit_price(item, product)
        shipping_class = str(item.get('shipping_class')
                             or product.get('shipping_class')
                             or SHIPPABLE).strip().lower()

        line = CartLine(
            product_id=str(item.get('product_id') or product.get('_id') or ''),
            quantity=quantity,
            unit_price=unit_price,
            subtotal=unit_price * quantity,
            weight_grams=_unit_weight(item, product, default_weight),
            shipping_class=shipping_class,
        )

        if shipping_class in NON_SHIPPABLE_CLASSES:
            non_shippable.append(line)
        else:
            shippable.append(line)

    return shippable, non_shippable


def _unit_price(item, product):
    """The price actually charged for one unit, as a Decimal.

    Prefers the price the caller already computed; falls back to the shared
    sale-price rules so delivery can never disagree with the cart about what
    an item cost. `app.pricing` deals in floats, so the conversion goes
    through `to_decimal` at this boundary and nowhere deeper.
    """
    if item.get('price') is not None:
        return to_decimal(item['price'])
    if product:
        from app.pricing import effective_price
        return to_decimal(effective_price(product))
    return ZERO


def _unit_weight(item, product, default_weight):
    """Per-unit weight in grams, falling back to the configured default.

    A product with no weight is the normal case in a catalogue that predates
    this feature, so the fallback is a configured number rather than zero -
    zero would quietly ship heavy orders at the lightest rate.
    """
    for source in (item.get('weight_grams'), product.get('weight_grams')):
        if source is None:
            continue
        try:
            weight = int(source)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            return weight
    return default_weight


# ── Step 4: billable weight ──────────────────────────────────────────────────
def _billable_weight(shippable, settings):
    total = sum(line.weight_grams * line.quantity for line in shippable)
    return max(total, settings['min_billable_weight_g'])


def _build_context(shippable, zone, billable_weight_g, settings, strict):
    zone = zone or None
    # A threshold that pays for itself two streets away loses money three
    # states over, so the zone's own figure wins whenever it has one.
    free_over = settings['free_over_amount']
    if zone is not None and zone.get('free_over_amount') is not None:
        free_over = to_decimal(zone['free_over_amount'])

    return QuoteContext(
        lines=shippable,
        currency=settings['currency'],
        zone=zone,
        zone_id=int(zone['zone_id']) if zone and zone.get('zone_id') is not None else None,
        zone_name=(zone or {}).get('name', 'Delivery'),
        shippable_subtotal=sum((line.subtotal for line in shippable), Decimal(ZERO)),
        billable_weight_g=billable_weight_g,
        free_over_amount=free_over,
        rounding_unit=to_decimal(settings['rounding_unit']),
        flat_rate_amount=to_decimal(settings['flat_rate_amount']),
        strict=strict,
        timeout_ms=settings['carrier_timeout_ms'],
    )


# ── Steps 5-9: strategy ──────────────────────────────────────────────────────
def _run_strategy(ctx, settings):
    """Run the configured strategy, falling back to a flat rate on failure.

    The timeout budget is advisory: a strategy that calls out to a carrier is
    handed `ctx.timeout_ms` and is expected to give it to its HTTP client,
    because nothing here can interrupt a call already in flight. What the
    service does enforce is the failure path - a strategy that raises, or
    overruns badly, or hands back something that isn't a quote, is replaced by
    `FlatRateStrategy` rather than left to break checkout.
    """
    name = settings['strategy']
    strategy_cls = STRATEGIES.get(name, STRATEGIES['zone'])

    if strategy_cls is FlatRateStrategy:
        return FlatRateStrategy().quote(ctx)

    started = time.monotonic()
    try:
        quote = strategy_cls().quote(ctx)
    except Exception:
        log.exception('Delivery strategy %r failed - falling back to flat rate', name)
        return _flat_fallback(ctx)

    elapsed_ms = (time.monotonic() - started) * 1000
    if ctx.timeout_ms and elapsed_ms > ctx.timeout_ms:
        log.warning('Delivery strategy %r took %.0fms (budget %dms)',
                    name, elapsed_ms, ctx.timeout_ms)

    if not isinstance(quote, DeliveryQuote):
        log.error('Delivery strategy %r returned %r - falling back to flat rate',
                  name, type(quote).__name__)
        return _flat_fallback(ctx)

    return quote


def _flat_fallback(ctx):
    """Last resort. If even the flat rate blows up, refuse rather than guess."""
    try:
        return FlatRateStrategy().quote(ctx)
    except Exception:
        log.exception('Flat-rate fallback failed')
        return unresolved(ctx, REASON_STRATEGY_UNAVAILABLE)


# ── Cache key ────────────────────────────────────────────────────────────────
def _cache_key(ctx, settings):
    """Key on everything the quote depends on, exactly.

    The brief asks for weight and subtotal brackets. These are the brackets:
    the exact billable weight and the exact subtotal. Coarser buckets are a
    liability here - one that straddles the free-delivery threshold, or a
    per-kg rate, hands a customer a fee that belongs to a different order. The
    win being bought is skipping repeated identical quotes across a cart
    render and its refreshes, and exact keys buy all of it.
    """
    return (
        ctx.zone_id,
        ctx.billable_weight_g,
        str(ctx.shippable_subtotal),
        str(ctx.free_over_amount),
        settings['strategy'],
    )
