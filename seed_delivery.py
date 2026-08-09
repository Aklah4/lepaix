"""Seed a starter set of delivery zones.

The rates below are PLACEHOLDERS. They are the shape of a working setup, not
advice on what to charge - open Admin → Delivery and put your real prices in.
What matters is that every state has a zone, because an address that matches
no zone cannot be priced and checkout will refuse the order.

Prints the plan and changes nothing unless you pass --write. Re-running is
safe: a zone whose name already exists is left exactly as it is, so your
edited prices are never overwritten.

    python seed_delivery.py                      # show the plan
    python seed_delivery.py --scope lagos        # Lagos only
    python seed_delivery.py --write              # actually create them
"""

import argparse
import os
from decimal import Decimal
from pathlib import Path

from pymongo import MongoClient

from app.delivery.repository import (DEFAULTS, SETTINGS_ID, ZoneRepository,
                                     build_zone_doc, money_to_bson)
from config import Config

BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / '.env'

# Every zone gets the same weight table: the first 2kg is covered by the base
# fee, 2-5kg adds a little, anything heavier adds more. Most fashion orders
# never leave the first row.
BRACKETS = [
    {'up_to_g': 2000, 'amount': Decimal('0')},
    {'up_to_g': 5000, 'amount': Decimal('1000')},
    {'up_to_g': None, 'amount': Decimal('2500')},
]

LAGOS_MAINLAND_AREAS = [
    'Ikeja', 'Yaba', 'Surulere', 'Agege', 'Alimosho', 'Ikotun', 'Egbeda',
    'Oshodi', 'Isolo', 'Ejigbo', 'Mushin', 'Shomolu', 'Bariga', 'Gbagada',
    'Maryland', 'Ojota', 'Ilupeju', 'Ogba', 'Magodo', 'Ketu', 'Festac',
    'Amuwo Odofin', 'Apapa', 'Ajegunle', 'Iyana Ipaja', 'Ipaja', 'Igando',
]

LAGOS_ISLAND_AREAS = [
    'Victoria Island', 'Ikoyi', 'Lekki', 'Lekki Phase 1', 'Ajah', 'Sangotedo',
    'Chevron', 'Oniru', 'Lagos Island', 'Obalende', 'Banana Island', 'Ilasan',
    'Ikate', 'Osapa London', 'Agungi', 'Idado', 'Awoyaya',
]

# (state, base fee). One catch-all zone per state, so nowhere is unpriceable.
STATE_TIERS = [
    # South-West - nearest, cheapest to reach from Lagos.
    (['Ogun', 'Oyo', 'Osun', 'Ondo', 'Ekiti'], Decimal('5000')),
    # South-East and South-South.
    (['Edo', 'Delta', 'Rivers', 'Bayelsa', 'Cross River', 'Akwa Ibom',
      'Anambra', 'Enugu', 'Imo', 'Abia', 'Ebonyi'], Decimal('6500')),
    # North-Central, including the FCT.
    (['FCT', 'Niger', 'Kwara', 'Kogi', 'Benue', 'Plateau', 'Nasarawa'],
     Decimal('6500')),
    # North-West and North-East - furthest, dearest.
    (['Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Sokoto', 'Zamfara', 'Jigawa',
      'Bauchi', 'Gombe', 'Borno', 'Yobe', 'Adamawa', 'Taraba'],
     Decimal('8000')),
]


def planned_zones(scope):
    """The zones this script would create, in the order it would create them."""
    zones = [
        {'name': 'Lagos Mainland', 'state': 'Lagos', 'areas': LAGOS_MAINLAND_AREAS,
         'is_state_fallback': False, 'base_fee': Decimal('2500')},
        {'name': 'Lagos Island & Lekki', 'state': 'Lagos', 'areas': LAGOS_ISLAND_AREAS,
         'is_state_fallback': False, 'base_fee': Decimal('3500')},
        # The catch-all for Lagos: Badagry, Epe, Ikorodu and anywhere not
        # listed above still get a price instead of a refused order.
        {'name': 'Lagos — anywhere else', 'state': 'Lagos', 'areas': [],
         'is_state_fallback': True, 'base_fee': Decimal('4000')},
    ]

    if scope == 'nationwide':
        for states, base_fee in STATE_TIERS:
            for state in states:
                zones.append({
                    'name': state if state == 'FCT' else f'{state} State',
                    'state': state,
                    'areas': [],
                    'is_state_fallback': True,
                    'base_fee': base_fee,
                })

    return zones


def to_document(zone):
    """Through the same builder the admin panel uses - one shape, one place."""
    return build_zone_doc(
        name=zone['name'],
        state=zone['state'],
        areas=zone['areas'],
        is_state_fallback=zone['is_state_fallback'],
        base_fee=zone['base_fee'],
        weight_mode='brackets',
        brackets=BRACKETS,
        included_kg=Decimal('0'),
        rate_per_kg=Decimal('0'),
        free_over_amount=None,   # falls back to the global setting
        active=True,
    )


def load_dotenv(path):
    if not path.exists():
        return
    with path.open('r', encoding='utf-8') as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def print_plan(zones, dbname):
    print(f"\n{len(zones)} zones would be created in database '{dbname}':\n")
    print(f"  {'ZONE':<26} {'STATE':<14} {'BASE FEE':>10}  COVERS")
    print(f"  {'-' * 26} {'-' * 14} {'-' * 10}  {'-' * 30}")
    for zone in zones:
        if zone['is_state_fallback']:
            covers = 'anywhere else in the state'
        else:
            covers = f"{len(zone['areas'])} areas: " + ', '.join(zone['areas'][:3]) + '…'
        print(f"  {zone['name']:<26} {zone['state']:<14} "
              f"{'NGN ' + format(zone['base_fee'], ',.0f'):>10}  {covers}")
    print('\n  Weight, on every zone: up to 2kg included, 2-5kg +NGN 1,000, '
          'above 5kg +NGN 2,500.')
    print('  Free-delivery threshold: not set. Turn it on in Admin -> Delivery '
          'when you want one.')
    print('\n  These are placeholder prices. Edit them in Admin -> Delivery.')


def seed(db, zones):
    repo = ZoneRepository(db)
    created, skipped = [], []

    for zone in zones:
        existing = db['delivery_zones'].find_one({'name': zone['name']})
        if existing:
            skipped.append(zone['name'])
            continue
        repo.insert_zone(to_document(zone))
        created.append(zone['name'])

    # Global settings, only if they have never been saved - never clobber
    # figures an admin has already tuned.
    if db.settings.find_one({'_id': SETTINGS_ID}) is None:
        repo.save_settings({
            'strategy': DEFAULTS['strategy'],
            'default_item_weight_g': DEFAULTS['default_item_weight_g'],
            'min_billable_weight_g': DEFAULTS['min_billable_weight_g'],
            'rounding_unit': money_to_bson(DEFAULTS['rounding_unit']),
            'flat_rate_amount': money_to_bson(DEFAULTS['flat_rate_amount']),
            'free_over_amount': None,
            'carrier_timeout_ms': DEFAULTS['carrier_timeout_ms'],
        })
        print('  Global delivery settings written.')

    try:
        repo.ensure_indexes()
        print('  Zone lookup indexes ensured.')
    except Exception as error:
        print(f'  Could not create indexes ({error}). Lookups still work, just slower.')

    return created, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scope', choices=('lagos', 'nationwide'), default='nationwide',
                        help='lagos = the three Lagos zones only; nationwide adds a '
                             'catch-all zone for every other state (default)')
    parser.add_argument('--write', action='store_true',
                        help='actually write to the database (otherwise just prints the plan)')
    parser.add_argument('--uri', help='MongoDB URI override')
    parser.add_argument('--dbname', help='MongoDB database name override')
    args = parser.parse_args()

    load_dotenv(DOTENV_PATH)
    config = Config()
    uri = args.uri or os.environ.get('MONGO_URI') or config.MONGO_URI
    dbname = args.dbname or os.environ.get('MONGO_DBNAME') or config.MONGO_DBNAME

    zones = planned_zones(args.scope)

    if not args.write:
        print_plan(zones, dbname)
        print('\nNothing was written. Re-run with --write to create these zones.')
        return

    client = MongoClient(uri)
    db = client[dbname]
    created, skipped = seed(db, zones)

    print(f"\nCreated {len(created)} zones in '{dbname}'.")
    if skipped:
        print(f'Left {len(skipped)} existing zones untouched: '
              f"{', '.join(skipped[:5])}{'…' if len(skipped) > 5 else ''}")
    print('Check them over in Admin -> Delivery and set your real prices.')


if __name__ == '__main__':
    main()
