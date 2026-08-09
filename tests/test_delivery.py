"""Delivery quoting tests.

Rules are tested in isolation against a hand-built context - no database, no
Flask, no fixtures. The integration tests drive the real `quote_delivery` with
a fake repository standing in for Mongo, so they exercise every step of the
calculation order without needing a server.
"""

from decimal import Decimal

import pytest

from app.delivery import quote_delivery, repository, strategies
from app.delivery.cache import clear_all
from app.delivery.money import round_to_unit
from app.delivery.resolver import normalize, resolve_zone
from app.delivery.rules import BaseFee, FreeOverThreshold, WeightAdjustment
from app.delivery.strategies import ZoneStrategy
from app.delivery.types import (REASON_NO_ADDRESS, REASON_UNRESOLVED_ZONE,
                                CartLine, LineAdjustment, QuoteContext)

# ── Fixtures: zones, settings, a fake repository ─────────────────────────────

LAGOS_MAINLAND = {
    'zone_id': 1,
    'name': 'Lagos Mainland',
    'state': 'Lagos',
    'state_norm': 'lagos',
    'areas': [{'name': 'Ikeja', 'norm': 'ikeja'}, {'name': 'Yaba', 'norm': 'yaba'}],
    'is_state_fallback': False,
    'base_fee': Decimal('2000'),
    'weight_mode': 'brackets',
    'brackets': [
        {'up_to_g': 1000, 'amount': Decimal('0')},
        {'up_to_g': 5000, 'amount': Decimal('750')},
        {'up_to_g': None, 'amount': Decimal('1500')},
    ],
    'free_over_amount': None,
    'active': True,
}

LAGOS_ANYWHERE = {
    'zone_id': 2,
    'name': 'Lagos (other areas)',
    'state': 'Lagos',
    'state_norm': 'lagos',
    'areas': [],
    'is_state_fallback': True,
    'base_fee': Decimal('3000'),
    'weight_mode': 'brackets',
    'brackets': [{'up_to_g': None, 'amount': Decimal('0')}],
    'free_over_amount': None,
    'active': True,
}

KANO = {
    'zone_id': 3,
    'name': 'Kano',
    'state': 'Kano',
    'state_norm': 'kano',
    'areas': [],
    'is_state_fallback': True,
    'base_fee': Decimal('5000'),
    'weight_mode': 'per_kg',
    'brackets': [],
    'included_kg': Decimal('2'),
    'rate_per_kg': Decimal('800'),
    # A threshold that pays for itself in Lagos would lose money here, so this
    # zone overrides the global figure with a higher one.
    'free_over_amount': Decimal('120000'),
    'active': True,
}

ALL_ZONES = [LAGOS_MAINLAND, LAGOS_ANYWHERE, KANO]


class FakeRepo:
    """The four reads `quote_delivery` makes, backed by a list of dicts."""

    def __init__(self, zones=ALL_ZONES, **overrides):
        self.zones = list(zones)
        self._settings = dict(repository.DEFAULTS)
        self._settings.update(overrides)

    def settings(self):
        return self._settings

    def zone_by_id(self, zone_id):
        return next((z for z in self.zones
                     if z['zone_id'] == int(zone_id) and z['active']), None)

    def zone_by_area(self, state_norm, area_norm):
        return next((z for z in self.zones
                     if z['state_norm'] == state_norm and z['active']
                     and any(a['norm'] == area_norm for a in z['areas'])), None)

    def state_fallback_zone(self, state_norm):
        return next((z for z in self.zones
                     if z['state_norm'] == state_norm and z['active']
                     and z.get('is_state_fallback')), None)


@pytest.fixture(autouse=True)
def _isolate_caches():
    """The caches are process-wide; no test may see another test's answer."""
    clear_all()
    yield
    clear_all()


@pytest.fixture
def repo(monkeypatch):
    """Point `quote_delivery` at an in-memory repository."""
    fake = FakeRepo()

    def _install(**overrides):
        fake._settings.update(overrides)
        monkeypatch.setattr(repository, 'default_repository', lambda: fake)
        return fake

    _install()
    return _install


def item(price='10000', quantity=1, weight_grams=None, shipping_class=None,
         product=None):
    """One enriched cart line, shaped the way the blueprints build them."""
    line = {'product_id': 'p1', 'quantity': quantity, 'price': Decimal(price)}
    if weight_grams is not None:
        line['weight_grams'] = weight_grams
    if shipping_class is not None:
        line['shipping_class'] = shipping_class
    if product is not None:
        line['product'] = product
        line.pop('price')
    return line


def ctx(**overrides):
    """A QuoteContext with sane defaults, for testing rules in isolation."""
    base = dict(
        lines=[CartLine('p1', 1, Decimal('10000'), Decimal('10000'), 500, 'shippable')],
        currency='NGN',
        zone=LAGOS_MAINLAND,
        zone_id=1,
        zone_name='Lagos Mainland',
        shippable_subtotal=Decimal('10000'),
        billable_weight_g=500,
        free_over_amount=None,
        rounding_unit=Decimal('50'),
        flat_rate_amount=Decimal('3000'),
        strict=False,
    )
    base.update(overrides)
    return QuoteContext(**base)


# ── Rules, in isolation ──────────────────────────────────────────────────────

class TestBaseFee:
    def test_charges_the_zones_base_fee(self):
        adjustment = BaseFee().apply(ctx(), Decimal('0'))
        assert adjustment.amount == Decimal('2000.00')
        assert adjustment.code == 'base_fee'
        assert adjustment.label == 'Base — Lagos Mainland'

    def test_no_zone_no_line(self):
        assert BaseFee().apply(ctx(zone=None), Decimal('0')) is None

    def test_zero_fee_adds_no_line(self):
        zone = dict(LAGOS_MAINLAND, base_fee=Decimal('0'))
        assert BaseFee().apply(ctx(zone=zone), Decimal('0')) is None


class TestWeightAdjustment:
    def test_bracket_lookup_picks_the_first_covering_bracket(self):
        adjustment = WeightAdjustment().apply(ctx(billable_weight_g=3000), Decimal('2000'))
        assert adjustment.amount == Decimal('750.00')
        assert adjustment.code == 'weight_adjustment'

    def test_lightest_bracket_is_free_and_adds_no_line(self):
        assert WeightAdjustment().apply(ctx(billable_weight_g=900), Decimal('2000')) is None

    def test_bracket_boundary_is_inclusive(self):
        # 1000g is "up to 1000g", not the next bracket up.
        assert WeightAdjustment().apply(ctx(billable_weight_g=1000), Decimal('0')) is None

    def test_unbounded_top_bracket_catches_anything(self):
        adjustment = WeightAdjustment().apply(ctx(billable_weight_g=40000), Decimal('0'))
        assert adjustment.amount == Decimal('1500.00')

    def test_past_the_top_of_a_bounded_table_uses_the_heaviest_bracket(self):
        zone = dict(LAGOS_MAINLAND, brackets=[{'up_to_g': 1000, 'amount': Decimal('300')}])
        adjustment = WeightAdjustment().apply(
            ctx(zone=zone, billable_weight_g=9999), Decimal('0'))
        assert adjustment.amount == Decimal('300.00')

    def test_per_kg_charges_only_the_excess(self):
        # 3.5kg - 2kg included = 1.5kg × ₦800
        adjustment = WeightAdjustment().apply(
            ctx(zone=KANO, billable_weight_g=3500), Decimal('5000'))
        assert adjustment.amount == Decimal('1200.00')

    def test_per_kg_under_the_included_weight_is_never_a_credit(self):
        assert WeightAdjustment().apply(
            ctx(zone=KANO, billable_weight_g=1500), Decimal('5000')) is None

    def test_labels_the_weight_in_kg(self):
        adjustment = WeightAdjustment().apply(ctx(billable_weight_g=3250), Decimal('0'))
        assert adjustment.label == 'Weight — 3.25 kg'


class TestFreeOverThreshold:
    def test_no_threshold_configured_does_nothing(self):
        assert FreeOverThreshold().apply(ctx(free_over_amount=None), Decimal('2000')) is None

    def test_below_threshold_does_nothing(self):
        context = ctx(free_over_amount=Decimal('50000'),
                      shippable_subtotal=Decimal('49999'))
        assert FreeOverThreshold().apply(context, Decimal('2000')) is None

    def test_exactly_at_threshold_is_free(self):
        context = ctx(free_over_amount=Decimal('50000'),
                      shippable_subtotal=Decimal('50000'))
        adjustment = FreeOverThreshold().apply(context, Decimal('2000'))
        assert adjustment.amount == Decimal('-2000.00')
        assert adjustment.code == 'free_over_threshold'

    def test_cancels_exactly_the_running_total(self):
        context = ctx(free_over_amount=Decimal('50000'),
                      shippable_subtotal=Decimal('80000'))
        adjustment = FreeOverThreshold().apply(context, Decimal('2750'))
        assert adjustment.amount == Decimal('-2750.00')

    def test_nothing_to_discount_adds_no_line(self):
        context = ctx(free_over_amount=Decimal('50000'),
                      shippable_subtotal=Decimal('80000'))
        assert FreeOverThreshold().apply(context, Decimal('0')) is None


# ── Rounding and clamping ────────────────────────────────────────────────────

class TestRounding:
    @pytest.mark.parametrize('amount,expected', [
        ('1010', '1000.00'),
        ('1025', '1050.00'),   # half-up
        ('1024.99', '1000.00'),
        ('0', '0.00'),
        ('2750', '2750.00'),
    ])
    def test_rounds_to_the_nearest_fifty(self, amount, expected):
        assert round_to_unit(Decimal(amount), Decimal('50')) == Decimal(expected)

    def test_breakdown_always_sums_to_the_amount(self):
        zone = dict(LAGOS_MAINLAND, base_fee=Decimal('1010'))
        quote = ZoneStrategy().quote(ctx(zone=zone))
        assert quote.amount == Decimal('1000.00')
        assert sum(line.amount for line in quote.breakdown) == quote.amount
        assert [line.code for line in quote.breakdown] == ['base_fee', 'rounding']


class OverDiscount:
    """A stand-in for a future promo rule that overshoots."""

    def apply(self, context, running):
        return LineAdjustment(label='Huge promo', amount=Decimal('-99999'), code='promo')


class TestClamp:
    def test_discounts_exceeding_the_fee_clamp_to_zero(self):
        quote = ZoneStrategy(rules=[BaseFee(), OverDiscount()]).quote(ctx())
        assert quote.amount == Decimal('0.00')
        assert quote.amount >= 0
        assert 'clamp_to_zero' in [line.code for line in quote.breakdown]
        assert sum(line.amount for line in quote.breakdown) == quote.amount


# ── Zone resolution ──────────────────────────────────────────────────────────

class TestNormalize:
    @pytest.mark.parametrize('raw,expected', [
        ('Ikeja', 'ikeja'),
        ('  IKEJA  ', 'ikeja'),
        ('Ikeja-G.R.A.', 'ikeja g r a'),
        ('Ikeja   GRA', 'ikeja gra'),
        (None, ''),
    ])
    def test_normalizes_both_sides_the_same_way(self, raw, expected):
        assert normalize(raw) == expected


class TestResolveZone:
    def test_tier_1_explicit_zone_wins(self):
        # The state says Kano; the customer picked Lagos Mainland from the
        # dropdown. What they picked wins.
        zone = resolve_zone({'zone_id': 1, 'state': 'Kano'}, FakeRepo())
        assert zone['zone_id'] == 1

    def test_tier_1_ignores_a_zone_that_no_longer_exists(self):
        zone = resolve_zone({'zone_id': 99, 'state': 'Lagos', 'city': 'Ikeja'}, FakeRepo())
        assert zone['zone_id'] == 1  # fell through to the (state, city) match

    def test_tier_2_exact_state_and_city(self):
        zone = resolve_zone({'state': 'lagos', 'city': 'IKEJA'}, FakeRepo())
        assert zone['zone_id'] == 1

    def test_tier_3_state_fallback(self):
        zone = resolve_zone({'state': 'Lagos', 'city': 'Somewhere Else'}, FakeRepo())
        assert zone['zone_id'] == 2

    def test_tier_4_no_match_is_none(self):
        assert resolve_zone({'state': 'Sokoto', 'city': 'Sokoto'}, FakeRepo()) is None

    def test_never_fuzzy_matches(self):
        # "Ikej" is one letter from a real area and must not resolve to it.
        # Lagos has a state fallback, so the honest answer is the fallback
        # zone, never Ikeja's cheaper rate.
        zone = resolve_zone({'state': 'Lagos', 'city': 'Ikej'}, FakeRepo())
        assert zone['zone_id'] == 2

    def test_no_state_is_unresolvable(self):
        assert resolve_zone({'city': 'Ikeja'}, FakeRepo()) is None


# ── The whole pipeline ───────────────────────────────────────────────────────

IKEJA = {'state': 'Lagos', 'city': 'Ikeja'}


class TestQuoteDelivery:
    def test_empty_cart_is_free_and_resolved(self, repo):
        quote = quote_delivery([], IKEJA)
        assert quote.amount == Decimal('0.00')
        assert quote.resolved is True
        assert quote.reason is None
        assert quote.breakdown == []

    def test_cart_of_only_non_shippable_items_is_free(self, repo):
        cart = [item(shipping_class='digital'),
                item(shipping_class='pickup'),
                item(shipping_class='free_shipping')]
        quote = quote_delivery(cart, IKEJA)
        assert quote.amount == Decimal('0.00')
        assert quote.resolved is True
        assert quote.billable_weight_g == 0

    def test_short_circuits_before_needing_an_address(self, repo):
        # Nothing to ship means nothing to resolve, even in strict mode.
        quote = quote_delivery([item(shipping_class='digital')], None, strict=True)
        assert quote.resolved is True
        assert quote.amount == Decimal('0.00')

    def test_prices_a_resolved_address(self, repo):
        quote = quote_delivery([item(weight_grams=800, quantity=1)], IKEJA)
        assert quote.zone_id == 1
        assert quote.amount == Decimal('2000.00')   # base only, under 1kg
        assert quote.resolved is True

    def test_weight_adds_to_the_base_fee(self, repo):
        quote = quote_delivery([item(weight_grams=1200, quantity=3)], IKEJA)
        assert quote.billable_weight_g == 3600
        assert quote.amount == Decimal('2750.00')   # 2000 base + 750 bracket

    def test_non_shippable_items_add_no_weight(self, repo):
        cart = [item(weight_grams=800),
                item(weight_grams=40000, shipping_class='digital')]
        quote = quote_delivery(cart, IKEJA)
        assert quote.billable_weight_g == 800
        assert quote.amount == Decimal('2000.00')

    def test_product_with_null_weight_falls_back_to_the_default(self, repo):
        product = {'_id': 'p9', 'name': 'Scarf', 'price': 10000.0}
        assert 'weight_grams' not in product
        quote = quote_delivery([item(product=product, quantity=2)], IKEJA)
        assert quote.billable_weight_g == 1000        # 2 × the 500g default
        assert quote.amount == Decimal('2000.00')

    def test_minimum_billable_weight_applies(self, repo):
        quote = quote_delivery([item(weight_grams=50)], IKEJA)
        assert quote.billable_weight_g == 500

    def test_per_kg_zone(self, repo):
        quote = quote_delivery([item(weight_grams=3500)], {'state': 'Kano'})
        assert quote.zone_id == 3
        assert quote.amount == Decimal('6200.00')    # 5000 + 1.5kg × 800

    def test_unresolvable_address_is_never_guessed(self, repo):
        quote = quote_delivery([item()], {'state': 'Sokoto', 'city': 'Sokoto'})
        assert quote.resolved is False
        assert quote.reason == REASON_UNRESOLVED_ZONE
        assert quote.amount == Decimal('0.00')
        assert quote.zone_id is None

    def test_missing_address_says_so(self, repo):
        quote = quote_delivery([item()], None)
        assert quote.resolved is False
        assert quote.reason == REASON_NO_ADDRESS

    def test_strict_unresolvable_address_blocks_the_order(self, repo):
        # This is the contract checkout depends on: `resolved is False` and no
        # fee. The blueprint refuses to insert an order when it sees this.
        quote = quote_delivery([item()], {'state': 'Sokoto'}, strict=True)
        assert quote.resolved is False
        assert quote.amount == Decimal('0.00')

    def test_flat_rate_strategy_needs_no_zone(self, repo):
        repo(strategy='flat')
        quote = quote_delivery([item()], {'state': 'Nowhere'})
        assert quote.resolved is True
        assert quote.amount == Decimal('3000.00')
        assert quote.zone_id is None


class TestFreeDeliveryThreshold:
    def test_one_unit_below_the_threshold_pays(self, repo):
        repo(free_over_amount=Decimal('50000'))
        quote = quote_delivery([item(price='49999', weight_grams=800)], IKEJA)
        assert quote.amount == Decimal('2000.00')

    def test_exactly_at_the_threshold_is_free(self, repo):
        repo(free_over_amount=Decimal('50000'))
        quote = quote_delivery([item(price='50000', weight_grams=800)], IKEJA)
        assert quote.amount == Decimal('0.00')
        assert 'free_over_threshold' in [line.code for line in quote.breakdown]

    def test_one_unit_above_the_threshold_is_free(self, repo):
        repo(free_over_amount=Decimal('50000'))
        quote = quote_delivery([item(price='50001', weight_grams=800)], IKEJA)
        assert quote.amount == Decimal('0.00')

    def test_a_markdown_below_the_threshold_pays_again(self, repo):
        # ₦60,000 ticket price, marked down to ₦45,000. The threshold sees the
        # discounted figure, so this order pays for delivery.
        repo(free_over_amount=Decimal('50000'))
        product = {'_id': 'p2', 'price': 60000.0, 'sale_price': 45000.0,
                   'weight_grams': 800}
        quote = quote_delivery([item(product=product)], IKEJA)
        assert quote.amount == Decimal('2000.00')

    def test_non_shippable_items_do_not_count_towards_the_threshold(self, repo):
        repo(free_over_amount=Decimal('50000'))
        cart = [item(price='30000', weight_grams=800),
                item(price='30000', shipping_class='digital')]
        quote = quote_delivery(cart, IKEJA)
        assert quote.amount == Decimal('2000.00')   # only ₦30,000 is shippable

    def test_a_zone_may_override_the_global_threshold(self, repo):
        # Global says free over ₦50,000; Kano says ₦120,000 and wins.
        repo(free_over_amount=Decimal('50000'))
        quote = quote_delivery([item(price='60000', weight_grams=1500)], {'state': 'Kano'})
        assert quote.amount == Decimal('5000.00')


class TestStrategyFallback:
    def test_a_failing_strategy_falls_back_to_the_flat_rate(self, repo, monkeypatch):
        class Exploding:
            def quote(self, context):
                raise RuntimeError('carrier API is down')

        monkeypatch.setitem(strategies.STRATEGIES, 'zone', Exploding)
        quote = quote_delivery([item()], IKEJA)
        assert quote.resolved is True
        assert quote.amount == Decimal('3000.00')
        assert [line.code for line in quote.breakdown] == ['flat_rate']

    def test_a_strategy_returning_nonsense_falls_back(self, repo, monkeypatch):
        class Confused:
            def quote(self, context):
                return {'amount': 12}

        monkeypatch.setitem(strategies.STRATEGIES, 'zone', Confused)
        quote = quote_delivery([item()], IKEJA)
        assert quote.resolved is True
        assert quote.amount == Decimal('3000.00')


class TestCaching:
    def test_a_strict_quote_ignores_the_cache(self, repo):
        fake = repo()
        cart = [item(weight_grams=800)]
        assert quote_delivery(cart, IKEJA).amount == Decimal('2000.00')

        # The admin raises the rate mid-session.
        fake.zones[0] = dict(LAGOS_MAINLAND, base_fee=Decimal('9000'))

        # The cart estimate may still be the cached figure...
        assert quote_delivery(cart, IKEJA).amount == Decimal('2000.00')
        # ...but the quote the order is created from never is.
        assert quote_delivery(cart, IKEJA, strict=True).amount == Decimal('9000.00')
