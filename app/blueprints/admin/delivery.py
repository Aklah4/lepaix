"""Admin: delivery zones and rates.

Everything a delivery costs is edited here and takes effect on the next quote.
No rate lives in code, and changing a price never needs a deploy.

This is the only part of the app besides `quote_delivery` that reaches into
`app.delivery` - it is the rate editor, which is a different job from quoting,
and it goes through the repository rather than touching the collection.
"""

from decimal import Decimal, InvalidOperation

from bson import ObjectId
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from app.db import get_db
from app.delivery.money import to_decimal
from app.delivery.repository import (DEFAULTS, ZoneRepository, build_zone_doc,
                                     money_to_bson)

admin_delivery_bp = Blueprint('admin_delivery', __name__, url_prefix='/admin/delivery')


def _auth_required():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))
    return None


def _repo():
    return ZoneRepository(get_db())


# ── Form parsing ─────────────────────────────────────────────────────────────
def _parse_money(raw, field, required=False, default=None):
    """Return (Decimal|None, error). Blank means "not set", not zero."""
    raw = (raw or '').strip().replace(',', '')
    if not raw:
        if required:
            return None, f'{field} is required.'
        return default, None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, f'{field} must be a number.'
    if value < 0:
        return None, f'{field} cannot be negative.'
    return value, None


def _parse_int(raw, field, default=0):
    raw = (raw or '').strip()
    if not raw:
        return default, None
    try:
        value = int(raw)
    except ValueError:
        return None, f'{field} must be a whole number.'
    if value < 0:
        return None, f'{field} cannot be negative.'
    return value, None


def _parse_areas(raw):
    """One area per line, or comma-separated - admins do both."""
    parts = []
    for line in (raw or '').replace(',', '\n').splitlines():
        line = line.strip()
        if line:
            parts.append(line)
    return parts


def _parse_brackets(raw):
    """Parse the weight table. One `up_to_grams: amount` per line.

    `*: 1500` is the unbounded top row. Returns (brackets, error); brackets are
    sorted by ceiling with the unbounded row last, so the first row whose
    ceiling covers a parcel is always the cheapest one that can.
    """
    brackets, unbounded = [], []
    for number, line in enumerate((raw or '').splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if ':' not in line:
            return None, f'Line {number} of the weight table needs a colon, e.g. "1000: 500".'
        ceiling_s, amount_s = line.split(':', 1)
        ceiling_s, amount_s = ceiling_s.strip(), amount_s.strip().replace(',', '')

        try:
            amount = Decimal(amount_s)
        except InvalidOperation:
            return None, f'Line {number} of the weight table: "{amount_s}" is not an amount.'
        if amount < 0:
            return None, f'Line {number} of the weight table cannot be negative.'

        if ceiling_s in ('*', 'any', 'above'):
            unbounded.append({'up_to_g': None, 'amount': amount})
            continue
        try:
            ceiling = int(ceiling_s)
        except ValueError:
            return None, f'Line {number} of the weight table: "{ceiling_s}" is not a weight in grams.'
        if ceiling <= 0:
            return None, f'Line {number} of the weight table needs a weight above zero.'
        brackets.append({'up_to_g': ceiling, 'amount': amount})

    brackets.sort(key=lambda b: b['up_to_g'])
    return brackets + unbounded[:1], None


def _brackets_to_text(brackets):
    """Render a stored table back into the textarea format."""
    lines = []
    for bracket in brackets or []:
        ceiling = bracket.get('up_to_g')
        amount = to_decimal(bracket.get('amount'))
        lines.append(f"{'*' if ceiling is None else ceiling}: {amount:f}")
    return '\n'.join(lines)


def _zone_from_form(form):
    """Build a storable zone document from the form. Returns (doc, error)."""
    name = form.get('name', '').strip()
    state = form.get('state', '').strip()
    if not name or not state:
        return None, 'A zone needs a name and a state.'

    base_fee, error = _parse_money(form.get('base_fee'), 'Base fee', required=True)
    if error:
        return None, error

    weight_mode = form.get('weight_mode', 'brackets')

    brackets, error = _parse_brackets(form.get('brackets'))
    if error:
        return None, error

    included_kg, error = _parse_money(form.get('included_kg'), 'Included weight',
                                      default=Decimal('0'))
    if error:
        return None, error

    rate_per_kg, error = _parse_money(form.get('rate_per_kg'), 'Rate per kg',
                                      default=Decimal('0'))
    if error:
        return None, error

    if weight_mode == 'per_kg' and rate_per_kg == 0:
        return None, 'A per-kg zone needs a rate per kg.'

    free_over, error = _parse_money(form.get('free_over_amount'),
                                    'Free delivery over')
    if error:
        return None, error

    return build_zone_doc(
        name=name, state=state,
        areas=_parse_areas(form.get('areas')),
        is_state_fallback=form.get('is_state_fallback') == 'on',
        base_fee=base_fee, weight_mode=weight_mode, brackets=brackets,
        included_kg=included_kg, rate_per_kg=rate_per_kg,
        free_over_amount=free_over,
        active=form.get('active', 'on') == 'on',
    ), None


# ── Zones ────────────────────────────────────────────────────────────────────
@admin_delivery_bp.route('/')
def index():
    guard = _auth_required()
    if guard:
        return guard

    repo = _repo()
    try:
        repo.ensure_indexes()
    except Exception:
        # Index creation is a nicety, not a precondition. A permissions
        # problem on the Mongo user must not take the page down.
        current_app.logger.exception('Could not ensure delivery zone indexes')

    zones = repo.all_zones()
    for zone in zones:
        zone['_id'] = str(zone['_id'])
        zone['base_fee_display'] = to_decimal(zone.get('base_fee'))
        zone['free_over_display'] = (to_decimal(zone['free_over_amount'])
                                     if zone.get('free_over_amount') is not None else None)
        zone['area_names'] = ', '.join(a['name'] for a in zone.get('areas', []))

    return render_template('admin/delivery/index.html',
                           zones=zones, settings=repo.settings(),
                           defaults=DEFAULTS)


@admin_delivery_bp.route('/zones/add', methods=['GET', 'POST'])
def add_zone():
    guard = _auth_required()
    if guard:
        return guard

    if request.method == 'POST':
        doc, error = _zone_from_form(request.form)
        if error:
            flash(error, 'error')
            return render_template('admin/delivery/edit_zone.html',
                                   zone=None, form=request.form)
        _repo().insert_zone(doc)
        flash(f"Zone \"{doc['name']}\" added.", 'success')
        return redirect(url_for('admin_delivery.index'))

    return render_template('admin/delivery/edit_zone.html', zone=None, form=None)


@admin_delivery_bp.route('/zones/<zone_oid>/edit', methods=['GET', 'POST'])
def edit_zone(zone_oid):
    guard = _auth_required()
    if guard:
        return guard

    repo = _repo()
    try:
        oid = ObjectId(zone_oid)
    except Exception:
        flash('Invalid zone.', 'error')
        return redirect(url_for('admin_delivery.index'))

    zone = repo.zone_by_oid(oid)
    if not zone:
        flash('Zone not found.', 'error')
        return redirect(url_for('admin_delivery.index'))

    if request.method == 'POST':
        doc, error = _zone_from_form(request.form)
        if error:
            flash(error, 'error')
            return render_template('admin/delivery/edit_zone.html',
                                   zone=_view(zone), form=request.form)
        repo.update_zone(oid, doc)
        flash(f"Zone \"{doc['name']}\" updated.", 'success')
        return redirect(url_for('admin_delivery.index'))

    return render_template('admin/delivery/edit_zone.html', zone=_view(zone), form=None)


@admin_delivery_bp.route('/zones/<zone_oid>/delete', methods=['POST'])
def delete_zone(zone_oid):
    guard = _auth_required()
    if guard:
        return guard

    try:
        oid = ObjectId(zone_oid)
    except Exception:
        flash('Invalid zone.', 'error')
        return redirect(url_for('admin_delivery.index'))

    repo = _repo()
    zone = repo.zone_by_oid(oid)
    if zone:
        repo.delete_zone(oid)
        flash(f"Zone \"{zone.get('name', '')}\" deleted. Orders already placed keep "
              'the fee they were quoted.', 'success')
    return redirect(url_for('admin_delivery.index'))


def _view(zone):
    """Shape a stored zone for the edit form."""
    view = dict(zone)
    view['_id'] = str(zone['_id'])
    view['areas_text'] = '\n'.join(a['name'] for a in zone.get('areas', []))
    view['brackets_text'] = _brackets_to_text(zone.get('brackets'))
    for key in ('base_fee', 'included_kg', 'rate_per_kg'):
        view[key] = to_decimal(zone.get(key))
    view['free_over_amount'] = (to_decimal(zone['free_over_amount'])
                                if zone.get('free_over_amount') is not None else '')
    return view


# ── Global settings ──────────────────────────────────────────────────────────
@admin_delivery_bp.route('/settings', methods=['POST'])
def save_settings():
    guard = _auth_required()
    if guard:
        return guard

    form = request.form
    values = {}

    strategy = form.get('strategy', 'zone')
    values['strategy'] = strategy if strategy in ('zone', 'flat') else 'zone'

    for field, label in (('default_item_weight_g', 'Default item weight'),
                         ('min_billable_weight_g', 'Minimum billable weight'),
                         ('carrier_timeout_ms', 'Carrier timeout')):
        value, error = _parse_int(form.get(field), label, DEFAULTS[field])
        if error:
            flash(error, 'error')
            return redirect(url_for('admin_delivery.index'))
        values[field] = value

    for field, label, required in (('rounding_unit', 'Rounding unit', True),
                                   ('flat_rate_amount', 'Flat rate', True),
                                   ('free_over_amount', 'Free delivery over', False)):
        value, error = _parse_money(form.get(field), label, required=required)
        if error:
            flash(error, 'error')
            return redirect(url_for('admin_delivery.index'))
        values[field] = money_to_bson(value)

    _repo().save_settings(values)
    flash('Delivery settings saved.', 'success')
    return redirect(url_for('admin_delivery.index'))
