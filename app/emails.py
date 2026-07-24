"""Order emails: customer confirmation and vendor notification.

Nothing in here may break checkout. `send_order_emails()` catches everything,
logs it, and returns; the SMTP conversation itself happens on a background
thread so the shopper never waits on the mail server.

Bodies are rendered up front, inside the request, because the background
thread has no request context - and the `money` template filter reads the
session, so it cannot be used in these templates. Amounts are formatted here
with `naira()` instead, since orders are stored in NGN.
"""

import threading

from flask import current_app, render_template
from flask_mail import Message

from app.extensions import mail


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


def _send_async(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            app.logger.info('Order email sent: %r -> %s',
                            msg.subject, ', '.join(msg.recipients))
        except Exception:
            app.logger.exception('Order email FAILED: %r -> %s',
                                 msg.subject, ', '.join(msg.recipients))


def _dispatch(app, msg):
    threading.Thread(target=_send_async, args=(app, msg), daemon=True).start()


def send_order_emails(order):
    """Queue the customer confirmation and the vendor notification.

    Safe to call from a request handler: it never raises and never blocks on
    SMTP. A missing mail configuration is logged and skipped.
    """
    app = current_app._get_current_object()
    messages = []

    try:
        if not app.config.get('MAIL_SERVER'):
            app.logger.warning('MAIL_SERVER unset - skipping emails for order %s',
                               order.get('order_number'))
            return

        order_number = order.get('order_number', '')
        customer = order.get('customer') or {}
        customer_email = (customer.get('email') or '').strip()
        vendor_email = (app.config.get('VENDOR_EMAIL') or '').strip()

        if customer_email:
            messages.append(Message(
                subject=f'Your Lepaix order {order_number}',
                recipients=[customer_email],
                body=_plain_text(order, for_vendor=False),
                html=render_template('emails/order_confirmation.html',
                                     order=order, customer=customer,
                                     naira=naira, variant=_variant),
            ))
        else:
            app.logger.warning('Order %s has no customer email', order_number)

        if vendor_email:
            messages.append(Message(
                subject=f'New order placed - {order_number}',
                recipients=[vendor_email],
                reply_to=customer_email or None,
                body=_plain_text(order, for_vendor=True),
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

    for msg in messages:
        try:
            _dispatch(app, msg)
        except Exception:
            app.logger.exception('Could not start mail thread for %r', msg.subject)


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
        if not app.config.get('MAIL_SERVER'):
            app.logger.warning('MAIL_SERVER unset - skipping shipping email for order %s',
                               order.get('order_number'))
            return

        order_number = order.get('order_number', '')
        customer = order.get('customer') or {}
        customer_email = (customer.get('email') or '').strip()
        if not customer_email:
            app.logger.warning('Order %s has no customer email - no shipping email',
                               order_number)
            return

        msg = Message(
            subject=f'Your Lepaix order {order_number} has shipped',
            recipients=[customer_email],
            body=_plain_text_shipped(order),
            html=render_template('emails/order_shipped.html',
                                 order=order, customer=customer,
                                 naira=naira, variant=_variant),
        )
    except Exception:
        app.logger.exception('Could not build shipping email for %s',
                             order.get('order_number'))
        return

    try:
        _dispatch(app, msg)
    except Exception:
        app.logger.exception('Could not start mail thread for %r', msg.subject)
