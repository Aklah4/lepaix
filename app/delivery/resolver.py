"""Address → zone. A plain function, tiered, most specific first.

The one rule that matters here: this never guesses. There is no fuzzy match,
no nearest-neighbour, no "Lagos-ish". A zone that is merely plausible is a
silent financial bug - every order to that address is mispriced and nobody
finds out until the month's delivery costs are reconciled. Returning None is
the correct answer for an address we have no rate for; the caller turns that
into "we don't deliver there yet" and blocks the order.
"""

import re
import unicodedata

from app.delivery.cache import zone_cache

# Everything that is not a letter, a digit or a space. Punctuation varies
# wildly in typed addresses ("Ikeja-GRA", "Ikeja G.R.A.") and carries no
# meaning for matching, so it goes.
_PUNCTUATION = re.compile(r'[^\w\s]', re.UNICODE)
_WHITESPACE = re.compile(r'\s+')


class _Miss:
    """Sentinel: distinguishes "cached as None" from "not cached"."""


_MISS = _Miss()


def normalize(value):
    """Lowercase, strip punctuation, collapse whitespace.

    Both sides of every comparison go through this - the stored zone areas at
    write time, the customer's typed address at read time - so the two can
    never drift apart.
    """
    if value is None:
        return ''
    text = unicodedata.normalize('NFKD', str(value))
    text = _PUNCTUATION.sub(' ', text.lower())
    return _WHITESPACE.sub(' ', text).strip()


def resolve_zone(address, repo, *, use_cache=True):
    """Return the zone document for `address`, or None.

    Tiers, in order:
      1. An explicit zone the customer picked from the dropdown.
      2. Exact match on (state, LGA/city), both normalized.
      3. The state-level fallback zone.
      4. None.

    `use_cache=False` forces a fresh read. Order creation uses it: the rate
    table a customer is actually charged from must be the one in the database
    at that moment, not one cached up to a minute ago.
    """
    if not address:
        return None

    # Tier 1 - the customer told us. Trust it over anything we infer, but
    # still confirm the zone exists and is active: the id arrives from a form
    # and a stale or deactivated zone must not price an order.
    zone_id = address.get('zone_id')
    if zone_id not in (None, ''):
        try:
            zone = repo.zone_by_id(int(zone_id))
        except (TypeError, ValueError):
            zone = None
        if zone is not None:
            return zone

    state_norm = normalize(address.get('state'))
    area_norm = normalize(address.get('lga') or address.get('city'))

    if not state_norm:
        return None

    cache_key = ('resolve', state_norm, area_norm)
    if use_cache:
        cached = zone_cache.get(cache_key, _MISS)
        if cached is not _MISS:
            return cached

    zone = None
    # Tier 2 - exact (state, LGA/city).
    if area_norm:
        zone = repo.zone_by_area(state_norm, area_norm)

    # Tier 3 - the state's catch-all zone.
    if zone is None:
        zone = repo.state_fallback_zone(state_norm)

    # Tier 4 is None, and None is cached too: an address we have no rate for
    # is asked about on every cart render, and the miss costs the same query
    # as the hit.
    zone_cache.set(cache_key, zone)
    return zone
