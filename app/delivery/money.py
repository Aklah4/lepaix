"""Decimal helpers shared by every part of the delivery module.

Money in here is `Decimal`, never `float` - a fee assembled from a base rate, a
per-kg rate and a percentage discount has to land on an exact figure the
customer is charged, and binary floats do not.

`to_decimal` is the one place a float is tolerated, and only because it is the
boundary: product prices in the products collection are stored as floats by
the rest of the app. Converting through `str()` keeps the value the shortest
decimal that round-trips (0.1 -> Decimal('0.1'), not 0.1000000000000000055).
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

try:  # pragma: no cover - bson is always present in the app, absent in unit tests
    from bson.decimal128 import Decimal128
except ImportError:  # pragma: no cover
    Decimal128 = None

CENTS = Decimal('0.01')
ZERO = Decimal('0.00')


def to_decimal(value, default=ZERO):
    """Coerce a stored value to Decimal. Returns `default` for None/garbage.

    Handles the four shapes money arrives in: Decimal (already right),
    Decimal128 (how this module stores it in Mongo), str/int (admin form
    input), and float (legacy documents written before this module existed).
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if Decimal128 is not None and isinstance(value, Decimal128):
        return value.to_decimal()
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def quantize_money(amount):
    """Snap to two decimal places, half-up - the way a person rounds."""
    return to_decimal(amount).quantize(CENTS, rounding=ROUND_HALF_UP)


def round_to_unit(amount, unit):
    """Round to the nearest `unit` (e.g. 50 -> nearest ₦50).

    A unit of 0 or less means "no unit rounding", which still quantizes to
    kobo so the stored amount is never a repeating fraction.
    """
    amount = to_decimal(amount)
    unit = to_decimal(unit)
    if unit <= 0:
        return quantize_money(amount)
    steps = (amount / unit).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return quantize_money(steps * unit)
