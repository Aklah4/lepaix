"""Data carried through a delivery quote. All frozen, all data-only.

Nothing in this file has a method that mutates or recalculates: a
`QuoteContext` is assembled once by the service and read by rules and
strategies, and a `DeliveryQuote` is the finished answer. Anything derived
(line subtotals, billable weight) is computed by the builder and stored, so a
rule can never see one number and a caller a different one.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

# Shipping classes a product can carry. Anything not in this set is treated as
# SHIPPABLE - a missing field must never silently make delivery free.
SHIPPABLE = 'shippable'
DIGITAL = 'digital'
PICKUP = 'pickup'
FREE_SHIPPING = 'free_shipping'

NON_SHIPPABLE_CLASSES = frozenset({DIGITAL, PICKUP, FREE_SHIPPING})


@dataclass(frozen=True)
class CartLine:
    """One shippable cart line, already priced and weighed."""

    product_id: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal           # unit_price × quantity, computed at build time
    weight_grams: int           # per unit, after the default-weight fallback
    shipping_class: str


@dataclass(frozen=True)
class LineAdjustment:
    label: str                  # customer-facing, e.g. "Base — Lagos Mainland"
    amount: Decimal             # signed; discounts negative
    code: str                   # machine-readable, e.g. "base_fee"


@dataclass(frozen=True)
class DeliveryQuote:
    amount: Decimal
    currency: str
    zone_id: int | None
    breakdown: list[LineAdjustment]
    billable_weight_g: int
    resolved: bool
    reason: str | None = None   # populated only when resolved is False


@dataclass(frozen=True)
class QuoteContext:
    """Everything a strategy needs to price a delivery, and nothing else."""

    lines: list[CartLine]           # shippable lines only
    currency: str
    zone: Mapping[str, Any] | None  # the zone configuration document
    zone_id: int | None
    zone_name: str
    shippable_subtotal: Decimal     # post-discount, shippable lines only
    billable_weight_g: int
    free_over_amount: Decimal | None
    rounding_unit: Decimal
    flat_rate_amount: Decimal
    strict: bool
    # Wall-clock budget handed to strategies that call something external.
    # An in-process strategy ignores it; a carrier-API strategy passes it
    # straight to its HTTP timeout.
    timeout_ms: int = 0


# Reasons a quote can come back unresolved. Short codes, not sentences - the
# blueprint owns the wording the shopper reads.
REASON_NO_ADDRESS = 'no_address'
REASON_UNRESOLVED_ZONE = 'unresolved_zone'
REASON_STRATEGY_UNAVAILABLE = 'strategy_unavailable'
