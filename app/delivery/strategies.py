"""How a quote gets priced. One protocol, two implementations.

`DeliveryStrategy` is the seam a third-party carrier API slots into later:
it takes a fully-built context and returns a finished quote, so adding one
means writing a class here and naming it in the delivery settings. No caller
of `quote_delivery` changes, and neither does its signature.

A strategy that talks to something external gets `ctx.timeout_ms` as its
budget and is expected to honour it; if it raises, overruns, or returns
something that isn't a quote, the service falls back to `FlatRateStrategy`.
A shopper is never shown a spinner because a carrier's API is having a day.
"""

from decimal import Decimal
from typing import Protocol

from app.delivery.money import ZERO, quantize_money, round_to_unit
from app.delivery.rules import DEFAULT_RULES, FreeOverThreshold
from app.delivery.types import (REASON_UNRESOLVED_ZONE, DeliveryQuote,
                                LineAdjustment, QuoteContext)


class DeliveryStrategy(Protocol):
    def quote(self, ctx: QuoteContext) -> DeliveryQuote: ...


def finalize_quote(ctx, breakdown, running):
    """Step 9 - clamp at zero, then round to the configured unit.

    Both steps append their own breakdown line when they change the figure, so
    the invariant every caller can rely on holds: the breakdown always sums to
    `amount`. A customer service agent reading an order's delivery lines can
    add them up and get the number the customer was charged.
    """
    breakdown = list(breakdown)

    if running < ZERO:
        # Discounts came to more than the fee. Delivery is free, never a
        # credit against the goods.
        breakdown.append(LineAdjustment(
            label='Adjusted to zero', amount=-running, code='clamp_to_zero'))
        running = ZERO

    rounded = round_to_unit(running, ctx.rounding_unit)
    if rounded != running:
        breakdown.append(LineAdjustment(
            label='Rounding', amount=quantize_money(rounded - running),
            code='rounding'))
        running = rounded

    return DeliveryQuote(
        amount=quantize_money(running),
        currency=ctx.currency,
        zone_id=ctx.zone_id,
        breakdown=breakdown,
        billable_weight_g=ctx.billable_weight_g,
        resolved=True,
        reason=None,
    )


def unresolved(ctx, reason):
    """A quote we refuse to make. Amount is zero and `resolved` says why."""
    return DeliveryQuote(
        amount=ZERO,
        currency=ctx.currency,
        zone_id=ctx.zone_id,
        breakdown=[],
        billable_weight_g=ctx.billable_weight_g,
        resolved=False,
        reason=reason,
    )


class ZoneStrategy:
    """Prices from the admin-editable zone rate tables."""

    def __init__(self, rules=None):
        self._rules = list(rules) if rules is not None else list(DEFAULT_RULES)

    def quote(self, ctx):
        if ctx.zone is None:
            # No rate table for this address. Not an error and not a zero -
            # an unpriceable delivery, which the caller has to handle.
            return unresolved(ctx, REASON_UNRESOLVED_ZONE)

        breakdown = []
        running = Decimal(ZERO)
        for rule in self._rules:
            adjustment = rule.apply(ctx, running)
            if adjustment is None:
                continue
            breakdown.append(adjustment)
            running += adjustment.amount

        return finalize_quote(ctx, breakdown, running)


class FlatRateStrategy:
    """One price everywhere. The configured fallback, and a valid choice.

    Needs no zone, so it resolves for any address - which is exactly why the
    service only reaches it when it is either configured as the strategy or
    standing in for one that failed, never as a guess at an address we could
    not place.
    """

    def quote(self, ctx):
        breakdown = []
        running = quantize_money(ctx.flat_rate_amount)
        if running != ZERO:
            breakdown.append(LineAdjustment(
                label='Delivery', amount=running, code='flat_rate'))

        # The threshold applies to a flat rate too: a shop that advertises
        # free delivery over a figure has to honour it whichever strategy
        # priced the order.
        adjustment = FreeOverThreshold().apply(ctx, running)
        if adjustment is not None:
            breakdown.append(adjustment)
            running += adjustment.amount

        return finalize_quote(ctx, breakdown, running)


STRATEGIES = {
    'zone': ZoneStrategy,
    'flat': FlatRateStrategy,
}
