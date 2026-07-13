from flask import Blueprint, abort, render_template

pages_bp = Blueprint('pages', __name__, url_prefix='/pages')

# Simple placeholder pages for footer links that don't have real content yet.
_PLACEHOLDER_PAGES = {
    'careers': {
        'title': 'Careers',
        'intro': "We're not hiring for specific roles right now, but we're always excited to hear from people who love fashion and great customer experiences.",
        'body': "Send your CV and a short note to hello@lepaix.com and we'll keep you in mind as the team grows.",
    },
    'locations': {
        'title': 'Locations',
        'intro': 'Lepaix is an online-first store.',
        'body': "We currently ship across Nigeria and don't yet have a physical showroom. Follow us on WhatsApp for pop-up shopping event announcements.",
    },
    'returns': {
        'title': 'Returns',
        'intro': 'We want you to love what you ordered.',
        'body': "We accept returns within 30 days of delivery for unworn, unwashed items with original tags attached. To start a return, message us on WhatsApp with your order number and reason, and we'll guide you through the next steps.",
    },
    'shipping': {
        'title': 'Shipping & Duties',
        'intro': "Here's what to expect once you place an order.",
        'body': 'We currently ship across Nigeria via courier, with delivery typically taking 2–5 business days depending on your location. For orders shipped outside Nigeria, any customs duties or import taxes are the responsibility of the customer and are not included in the checkout total.',
    },
    'privacy': {
        'title': 'Privacy Policy',
        'intro': 'Your privacy matters to us.',
        'body': 'Lepaix collects only the information needed to process your order and improve your shopping experience — your name, delivery address, and contact details. We never sell your data to third parties. A full privacy policy will be published here soon.',
    },
    'terms': {
        'title': 'Terms & Conditions',
        'intro': 'The basics of shopping with us.',
        'body': 'By placing an order with Lepaix, you agree that all orders are subject to availability, prices are listed as shown at checkout, and payment is required in full before dispatch. A complete terms of service will be published here soon.',
    },
    'refer': {
        'title': 'Refer a Friend',
        'intro': 'Love shopping with Lepaix? Tell a friend.',
        'body': "We're working on a formal referral rewards program — check back soon, or message us on WhatsApp to ask about current promotions.",
    },
}


@pages_bp.route('/about')
def about():
    return render_template('pages/about.html')


@pages_bp.route('/contact')
def contact():
    return render_template('pages/contact.html')


@pages_bp.route('/size-guide')
def size_guide():
    return render_template('pages/size_guide.html')


@pages_bp.route('/faq')
def faq():
    return render_template('pages/faq.html')


@pages_bp.route('/<slug>')
def placeholder(slug):
    page = _PLACEHOLDER_PAGES.get(slug)
    if not page:
        abort(404)
    return render_template('pages/placeholder.html', **page)
