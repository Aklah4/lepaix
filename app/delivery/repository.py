"""Mongo access for delivery zones and the global delivery settings.

Rates live in the database, not in code: the admin panel edits them and the
next quote picks them up. Nothing here decides what a delivery costs - it only
stores and fetches the configuration the rules are driven by.

Money is stored as BSON Decimal128, so a rate written as 2500.50 reads back as
exactly 2500.50. The rest of the app stores prices as floats; this collection
does not inherit that.

The quoting path uses only the read methods, through `quote_delivery`. The
write methods exist for the admin blueprint, which is the rate editor - a
different job from quoting, and the only other caller in the codebase.
"""

from datetime import datetime, timezone
from decimal import Decimal

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, ReturnDocument

from app.delivery.cache import clear_all, settings_cache
from app.delivery.money import quantize_money, to_decimal
from app.delivery.resolver import normalize

ZONES = 'delivery_zones'
SETTINGS_ID = 'delivery'

# Global fallbacks. Every one of these is overridable from the admin panel;
# they are what a shop that has never opened the delivery settings page gets.
DEFAULTS = {
    'strategy': 'zone',           # 'zone' | 'flat'
    'currency': 'NGN',
    'default_item_weight_g': 500,  # a folded garment; used when a product has no weight
    'min_billable_weight_g': 500,  # nobody dispatches a rider for less
    'free_over_amount': None,      # None = no global threshold
    'rounding_unit': Decimal('50'),  # ₦50 - the smallest note anyone carries
    'flat_rate_amount': Decimal('3000'),
    'carrier_timeout_ms': 2500,
}

_MONEY_SETTINGS = ('free_over_amount', 'rounding_unit', 'flat_rate_amount')
_INT_SETTINGS = ('default_item_weight_g', 'min_billable_weight_g', 'carrier_timeout_ms')


def money_to_bson(value):
    """Decimal → Decimal128 for storage. None stays None."""
    if value is None:
        return None
    return Decimal128(quantize_money(value))


class ZoneRepository:
    """Reads and writes delivery configuration. One instance per request is fine."""

    def __init__(self, db):
        self._db = db

    # ── Reads (the quoting path) ─────────────────────────────────────────────
    def settings(self):
        """Global delivery settings, defaults filled in, money as Decimal."""
        cached = settings_cache.get('settings')
        if cached is not None:
            return cached

        stored = self._db.settings.find_one({'_id': SETTINGS_ID}) or {}
        merged = dict(DEFAULTS)
        for key in DEFAULTS:
            if key in stored and stored[key] is not None:
                merged[key] = stored[key]

        for key in _MONEY_SETTINGS:
            # free_over_amount is legitimately null - "no threshold" is not
            # the same as "a threshold of zero", which would make every
            # delivery free.
            if merged.get(key) is None:
                merged[key] = None
            else:
                merged[key] = to_decimal(merged[key])
        for key in _INT_SETTINGS:
            try:
                merged[key] = max(0, int(merged[key]))
            except (TypeError, ValueError):
                merged[key] = DEFAULTS[key]

        if merged.get('strategy') not in ('zone', 'flat'):
            merged['strategy'] = DEFAULTS['strategy']

        settings_cache.set('settings', merged)
        return merged

    def zone_by_id(self, zone_id):
        return self._db[ZONES].find_one({'zone_id': int(zone_id), 'active': True})

    def zone_by_area(self, state_norm, area_norm):
        return self._db[ZONES].find_one({
            'state_norm': state_norm,
            'areas.norm': area_norm,
            'active': True,
        })

    def state_fallback_zone(self, state_norm):
        return self._db[ZONES].find_one({
            'state_norm': state_norm,
            'is_state_fallback': True,
            'active': True,
        })

    def active_zones(self):
        """Every active zone, for the customer-facing dropdown."""
        return list(self._db[ZONES].find({'active': True}).sort('name', ASCENDING))

    # ── Writes (the admin rate editor) ───────────────────────────────────────
    def all_zones(self):
        return list(self._db[ZONES].find().sort([('state', ASCENDING), ('name', ASCENDING)]))

    def zone_by_oid(self, oid):
        return self._db[ZONES].find_one({'_id': oid})

    def next_zone_id(self):
        """Allocate a stable integer id, the same way order numbers are allocated.

        Orders snapshot `zone_id`, and a snapshot has to stay readable years
        later - an incrementing integer survives a collection being restored
        or re-imported in a way an ObjectId does not.
        """
        counter = self._db.counters.find_one_and_update(
            {'_id': 'delivery_zone_id'},
            {'$inc': {'seq': 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(counter.get('seq', 1))

    def insert_zone(self, doc):
        doc = dict(doc)
        doc['zone_id'] = self.next_zone_id()
        doc['created_at'] = datetime.now(timezone.utc)
        result = self._db[ZONES].insert_one(doc)
        clear_all()
        return result.inserted_id

    def update_zone(self, oid, doc):
        doc = dict(doc)
        doc['updated_at'] = datetime.now(timezone.utc)
        self._db[ZONES].update_one({'_id': oid}, {'$set': doc})
        clear_all()

    def delete_zone(self, oid):
        self._db[ZONES].delete_one({'_id': oid})
        clear_all()

    def save_settings(self, values):
        self._db.settings.update_one(
            {'_id': SETTINGS_ID}, {'$set': values}, upsert=True)
        clear_all()

    def ensure_indexes(self):
        """Zone lookups must never scan the collection."""
        self._db[ZONES].create_index([('state_norm', ASCENDING),
                                      ('areas.norm', ASCENDING)],
                                     name='zone_state_area')
        self._db[ZONES].create_index([('state_norm', ASCENDING),
                                      ('is_state_fallback', ASCENDING)],
                                     name='zone_state_fallback')
        self._db[ZONES].create_index([('zone_id', ASCENDING)],
                                     name='zone_id_unique', unique=True)


def build_zone_doc(*, name, state, areas, is_state_fallback, base_fee,
                   weight_mode, brackets, included_kg, rate_per_kg,
                   free_over_amount, active):
    """Assemble a storable zone document, normalizing both match keys.

    The normalized forms are written here, at the only place zones are
    created, so the indexed columns can never fall out of step with the
    display values an admin typed.
    """
    area_names = [a.strip() for a in areas if a and a.strip()]
    return {
        'name': name.strip(),
        'state': state.strip(),
        'state_norm': normalize(state),
        'areas': [{'name': a, 'norm': normalize(a)} for a in area_names],
        'is_state_fallback': bool(is_state_fallback),
        'base_fee': money_to_bson(base_fee),
        'weight_mode': weight_mode if weight_mode in ('brackets', 'per_kg') else 'brackets',
        'brackets': [{'up_to_g': b['up_to_g'], 'amount': money_to_bson(b['amount'])}
                     for b in brackets],
        'included_kg': money_to_bson(included_kg),
        'rate_per_kg': money_to_bson(rate_per_kg),
        'free_over_amount': money_to_bson(free_over_amount),
        'active': bool(active),
    }


def default_repository():
    """The repository the quoting path uses. Patched wholesale in tests."""
    from app.db import get_db
    return ZoneRepository(get_db())
