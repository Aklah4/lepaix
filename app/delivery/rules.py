"""The rules pipeline: base fee, weight adjustment, free-over-threshold.

A rule sees the context and the running total, and returns one adjustment or
None. Ordering is the list order in `DEFAULT_RULES` - never a conditional
buried inside a rule asking what ran before it. Adding a surcharge later means
writing a class and putting it in the list at the right position; it does not
mean editing any of these.

Only the three rules the brief asks for exist. Surcharges (fragile, oversized,
remote-area, cash-on-delivery) have a documented slot in the order and no
implementation until they are actually wanted.
"""

from decimal import Decimal
from typing import Protocol

from app.delivery.money import ZERO, quantize_money, to_decimal
from app.delivery.types import LineAdjustment

# What the free-delivery threshold is measured against.
#
# The post-discount subtotal of SHIPPABLE lines only. Two deliberate choices:
#
#   post-discount - the customer's own view of what they spent is the amount
#   they were charged, not the pre-markdown ticket price. A sale that takes an
#   order under the threshold takes it under the threshold.
#
#   shippable only - a digital or store-pickup item costs nothing to deliver,
#   so letting it push an order over the threshold would buy the delivery of
#   the physical items with money that never covered any delivery.
FREE_THRESHOLD_BASIS = 'shippable_post_discount_subtotal'

KG = Decimal('1000')


class Rule(Protocol):
    def apply(self, ctx, running: Decimal) -> LineAdjustment | None: ...


class BaseFee:
    """The zone's flat starting price."""

    def apply(self, ctx, running):
        if ctx.zone is None:
            return None
        amount = to_decimal(ctx.zone.get('base_fee'))
        if amount == ZERO:
            return None
        return LineAdjustment(
            label=f'Base — {ctx.zone_name}',
            amount=quantize_money(amount),
            code='base_fee',
        )


class WeightAdjustment:
    """What the parcel's weight adds on top of the base fee.

    Two shapes, chosen per zone by `weight_mode`:

      brackets - a table of "up to N grams costs X". The first bracket whose
      ceiling covers the parcel wins.

      per_kg   - `(billable_kg - included_kg) × rate_per_kg`, floored at zero
      so a light parcel is never a credit.
    """

    def apply(self, ctx, running):
        if ctx.zone is None:
            return None

        weight_g = ctx.billable_weight_g
        if ctx.zone.get('weight_mode') == 'per_kg':
            amount = self._per_kg(ctx, weight_g)
        else:
            amount = self._bracket(ctx, weight_g)

        if amount is None or amount == ZERO:
            return None

        kg = (Decimal(weight_g) / KG).quantize(Decimal('0.01'))
        return LineAdjustment(
            label=f'Weight — {kg} kg',
            amount=quantize_money(amount),
            code='weight_adjustment',
        )

    def _bracket(self, ctx, weight_g):
        brackets = ctx.zone.get('brackets') or []
        if not brackets:
            return None
        for bracket in brackets:
            ceiling = bracket.get('up_to_g')
            if ceiling is None or weight_g <= int(ceiling):
                return to_decimal(bracket.get('amount'))
        # Past the top of the table. Charging the heaviest bracket is the
        # conservative read of a table whose author forgot an unbounded row -
        # it under-charges rather than refusing an order, and the admin form
        # steers towards leaving the last row unbounded.
        return to_decimal(brackets[-1].get('amount'))

    def _per_kg(self, ctx, weight_g):
        rate = to_decimal(ctx.zone.get('rate_per_kg'))
        if rate == ZERO:
            return None
        included_kg = to_decimal(ctx.zone.get('included_kg'))
        billable_kg = Decimal(weight_g) / KG
        extra_kg = billable_kg - included_kg
        if extra_kg <= ZERO:
            return None
        return extra_kg * rate


class FreeOverThreshold:
    """Zero the delivery once the shippable subtotal reaches the threshold.

    Returns the exact negative of the running total, so it cancels whatever
    the base fee and weight came to rather than assuming a figure. At the
    threshold exactly, delivery is free - "free over ₦50,000" reads as
    including ₦50,000 to every customer who has ever seen the banner.
    """

    def apply(self, ctx, running):
        threshold = ctx.free_over_amount
        if threshold is None:
            return None
        if ctx.shippable_subtotal < threshold:
            return None
        if running <= ZERO:
            return None
        return LineAdjustment(
            label=f'Free delivery over {threshold:,.0f}',
            amount=-quantize_money(running),
            code='free_over_threshold',
        )


# The order is the calculation order. Surcharges, when they exist, go between
# WeightAdjustment and FreeOverThreshold - see the note in service.py.
DEFAULT_RULES = [BaseFee(), WeightAdjustment(), FreeOverThreshold()]
