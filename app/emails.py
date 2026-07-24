"""Order emails: customer confirmation and vendor notification.

Delivery goes through Resend's HTTPS API rather than SMTP. Railway blocks
outbound SMTP ports, so smtp.gmail.com is unreachable from production; Resend
sends over port 443, which is always open, and works locally too.

Nothing in here may break checkout. The send functions catch everything, log
it, and return; the network call itself happens on a background thread so the
shopper never waits on it.

Bodies are rendered up front, inside the request, because the background
thread has no request context - and the `money` template filter reads the
session, so it cannot be used in these templates. Amounts are formatted here
with `naira()` instead, since orders are stored in NGN.
"""

import json
import threading
import urllib.error
import urllib.request

from flask import current_app, render_template

RESEND_ENDPOINT = 'https://api.resend.com/emails'


def naira(amount):
    """Format a stored (NGN) amount for display in an email."""
    try:
        return f"₦{float(amount):,.2f}"
    except (TypeError, ValueError):
        return "₦0.00"


def _variant(item):
    """'Size 42 / #1a2340' - whichever of the two the line item actually has."""
    bits = []
    if item.get('size'):
        bits.append(f"Size {item['size']}")
    if item.get('color'):
        bits.append(str(item['color']))
    return ' / '.join(bits)


def _plain_text(order, for_vendor):
    """Plain-text alternative, kept in step with the HTML templates."""
    customer = order.get('customer') or {}
    lines = []

    if for_vendor:
        lines += [
            f"New order placed - {order.get('order_number', '')}",
            '',
            'CUSTOMER',
            f"  Name:    {customer.get('name', '')}",
            f"  Email:   {customer.get('email', '')}",
            f"  Phone:   {customer.get('phone', '') or '-'}",
            '',
        ]
    else:
        lines += [
            f"Thank you for your order, {customer.get('name', '').split(' ')[0]}".rstrip(),
            '',
            f"Order {order.get('order_number', '')} is confirmed. We will email you "
            'again as soon as it ships.',
            '',
        ]

    lines.append('ITEMS')
    for item in order.get('items', []):
        variant = _variant(item)
        suffix = f" ({variant})" if variant else ''
        lines.append(
            f"  {item.get('quantity', 1)} x {item.get('product_name', '')}{suffix}"
            f" - {naira(item.get('subtotal', 0))}"
        )

    lines += [
        '',
        f"Subtotal: {naira(order.get('subtotal', 0))}",
        f"Shipping: {naira(order.get('shipping_cost', 0))}",
        f"Total:    {naira(order.get('total', 0))}",
        '',
        'SHIPPING ADDRESS',
        f"  {customer.get('name', '')}",
        f"  {customer.get('address', '')}",
        f"  {customer.get('city', '')}, {customer.get('country', '')}",
    ]

    if order.get('notes'):
        lines += ['', 'ORDER NOTES', f"  {order['notes']}"]

    lines += ['', 'Lepaix']
    return '\n'.join(lines)


def _post_resend(app, payload):
    """POST one email to Resend. Returns (status_code, body_text)."""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(RESEND_ENDPOINT, data=data, method='POST', headers={
        'Authorization': f"Bearer {app.config.get('RESEND_API_KEY', '')}",
        'Content-Type': 'application/json',
    })
    timeout = app.config.get('MAIL_TIMEOUT', 20)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode('utf-8', 'replace')


def _send_async(app, payload):
    subject = payload.get('subject', '')
    to = ', '.join(payload.get('to', []))
    try:
        status, body = _post_resend(app, payload)
        if 200 <= status < 300:
            app.logger.info('Order email sent: %r -> %s', subject, to)
        else:
            app.logger.error('Order email FAILED (%s): %r -> %s | %s',
                             status, subject, to, body[:300])
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        app.logger.error('Order email FAILED (%s): %r -> %s | %s',
                         e.code, subject, to, detail)
    except Exception:
        app.logger.exception('Order email FAILED: %r -> %s', subject, to)


def _dispatch(app, payload):
    threading.Thread(target=_send_async, args=(app, payload), daemon=True).start()


def _build(app, subject, recipients, html, text, reply_to=None):
    """Assemble a Resend payload. `from` must be on a Resend-verified domain."""
    payload = {
        'from': (app.config.get('MAIL_DEFAULT_SENDER') or '').strip(),
        'to': recipients,
        'subject': subject,
        'html': html,
        'text': text,
    }
    if reply_to:
        payload['reply_to'] = reply_to
    return payload


def _mail_ready(app, order_number):
    """True when Resend is configured. Logs and returns False otherwise."""
    if not app.config.get('RESEND_API_KEY'):
        app.logger.warning('RESEND_API_KEY unset - skipping emails for order %s',
                           order_number)
        return False
    if not (app.config.get('MAIL_DEFAULT_SENDER') or '').strip():
        app.logger.warning('MAIL_DEFAULT_SENDER unset - skipping emails for order %s',
                           order_number)
        return False
    return True


def send_order_emails(order):
    """Queue the customer confirmation and the vendor notification.

    Safe to call from a request handler: it never raises and never blocks on
    SMTP. A missing mail configuration is logged and skipped.
    """
    app = current_app._get_current_object()
    messages = []

    try:
        if not _mail_ready(app, order.get('order_number')):
            return

        order_number = order.get('order_number', '')
        customer = order.get('customer') or {}
        customer_email = (customer.get('email') or '').strip()
        vendor_email = (app.config.get('VENDOR_EMAIL') or '').strip()

        if customer_email:
            messages.append(_build(
                app,
                subject=f'Your Lepaix order {order_number}',
                recipients=[customer_email],
                text=_plain_text(order, for_vendor=False),
                html=render_template('emails/order_confirmation.html',
                                     order=order, customer=customer,
                                     naira=naira, variant=_variant),
            ))
        else:
            app.logger.warning('Order %s has no customer email', order_number)

        if vendor_email:
            messages.append(_build(
                app,
                subject=f'New order placed - {order_number}',
                recipients=[vendor_email],
                reply_to=customer_email or None,
                text=_plain_text(order, for_vendor=True),
                html=render_template('emails/new_order_notification.html',
                                     order=order, customer=customer,
                                     naira=naira, variant=_variant),
            ))
        else:
            app.logger.warning('VENDOR_EMAIL unset - no vendor notification sent')

    except Exception:
        # Rendering or config problem: log it, but let the order stand.
        app.logger.exception('Could not build order emails for %s',
                             order.get('order_number'))
        return

    for payload in messages:
        try:
            _dispatch(app, payload)
        except Exception:
            app.logger.exception('Could not start mail thread for %r',
                                 payload.get('subject'))


def _plain_text_shipped(order):
    """Plain-text alternative for the shipping notice."""
    customer = order.get('customer') or {}
    lines = [
        f"Good news, {customer.get('name', '').split(' ')[0]} - your order has shipped".rstrip(),
        '',
        f"Order {order.get('order_number', '')} is on its way.",
    ]

    tracking = (order.get('tracking_number') or '').strip()
    carrier = (order.get('carrier') or '').strip()
    if tracking:
        lines += ['', 'TRACKING', f"  {carrier + ': ' if carrier else ''}{tracking}"]

    lines.append('')
    lines.append('ITEMS')
    for item in order.get('items', []):
        variant = _variant(item)
        suffix = f" ({variant})" if variant else ''
        lines.append(
            f"  {item.get('quantity', 1)} x {item.get('product_name', '')}{suffix}"
        )

    lines += [
        '',
        'SHIPPING TO',
        f"  {customer.get('name', '')}",
        f"  {customer.get('address', '')}",
        f"  {customer.get('city', '')}, {customer.get('country', '')}",
        '',
        'Lepaix',
    ]
    return '\n'.join(lines)


def send_shipping_email(order):
    """Tell the customer their order shipped. Never raises, never blocks.

    Safe to call from the status-update handler; a missing mail configuration
    or customer email is logged and skipped.
    """
    app = current_app._get_current_object()

    try:
        if not _mail_ready(app, order.get('order_number')):
            return

        order_number = order.get('order_number', '')
        customer = order.get('customer') or {}
        customer_email = (customer.get('email') or '').strip()
        if not customer_email:
            app.logger.warning('Order %s has no customer email - no shipping email',
                               order_number)
            return

        payload = _build(
            app,
            subject=f'Your Lepaix order {order_number} has shipped',
            recipients=[customer_email],
            text=_plain_text_shipped(order),
            html=render_template('emails/order_shipped.html',
                                 order=order, customer=customer,
                                 naira=naira, variant=_variant),
        )
    except Exception:
        app.logger.exception('Could not build shipping email for %s',
                             order.get('order_number'))
        return

    try:
        _dispatch(app, payload)
    except Exception:
        app.logger.exception('Could not start mail thread for %r',
                             payload.get('subject'))
