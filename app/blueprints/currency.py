from flask import Blueprint, redirect, request, session, url_for

currency_bp = Blueprint('currency', __name__, url_prefix='/currency')

SUPPORTED_CURRENCIES = {'NGN', 'USD'}


@currency_bp.route('/set/<code>')
def set_currency(code):
    code = code.upper()
    if code in SUPPORTED_CURRENCIES:
        session['currency'] = code
        session.modified = True
    return redirect(request.referrer or url_for('index.index'))
