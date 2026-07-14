import os
import secrets
import cloudinary
from flask import Flask, url_for
from .db import init_db
from .extensions import limiter, csrf
from config import get_config


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    if not app.config.get('SECRET_KEY'):
        if app.config.get('DEBUG'):
            app.config['SECRET_KEY'] = secrets.token_hex(32)
            print('WARNING: SECRET_KEY not set — using a random key for this '
                  'process only. Sessions will not persist across restarts. '
                  'Set SECRET_KEY in .env to fix this.')
        else:
            raise RuntimeError('SECRET_KEY environment variable must be set outside of debug mode.')

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Configure Cloudinary
    cloudinary.config(
        cloud_name=app.config['CLOUDINARY_CLOUD_NAME'],
        api_key=app.config['CLOUDINARY_API_KEY'],
        api_secret=app.config['CLOUDINARY_API_SECRET'],
        secure=True,
    )

    # Initialize database connection
    init_db(app)

    limiter.init_app(app)
    csrf.init_app(app)

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.quilljs.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.quilljs.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        return response

    @app.template_filter('image_url')
    def image_url_filter(path):
        if not path:
            return ''
        if path.startswith('http'):
            return path
        return url_for('static', filename=f'uploads/{path}')

    DEFAULT_NGN_PER_USD = 1500

    def _ngn_per_usd():
        from flask import g
        if not hasattr(g, '_ngn_per_usd'):
            from app.db import get_db
            settings = get_db().settings.find_one({'_id': 'site'}) or {}
            g._ngn_per_usd = settings.get('ngn_per_usd') or DEFAULT_NGN_PER_USD
        return g._ngn_per_usd

    @app.template_filter('money')
    def money_filter(amount):
        from flask import session
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        if session.get('currency', 'NGN') == 'USD':
            return f"${amount / _ngn_per_usd():,.2f}"
        return f"₦{amount:,.2f}"

    # Register blueprints
    from app.blueprints.admin.auth import admin_auth_bp, admin_bp
    from app.blueprints.admin.products import admin_products_bp
    from app.blueprints.admin.orders import admin_orders_bp
    from app.blueprints.admin.settings import admin_settings_bp
    from app.blueprints.admin.blog import admin_blog_bp
    from app.blueprints.admin.categories import admin_categories_bp
    from app.blueprints.index import index_bp
    from app.blueprints.products import products_bp
    from app.blueprints.pages import pages_bp
    from app.blueprints.blog import blog_bp
    from app.blueprints.cart import cart_bp
    from app.blueprints.checkout import checkout_bp
    from app.blueprints.wishlist import wishlist_bp
    from app.blueprints.currency import currency_bp

    app.register_blueprint(admin_auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_products_bp)
    app.register_blueprint(admin_orders_bp)
    app.register_blueprint(admin_settings_bp)
    app.register_blueprint(admin_blog_bp)
    app.register_blueprint(admin_categories_bp)
    app.register_blueprint(index_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(wishlist_bp)
    app.register_blueprint(currency_bp)

    @app.context_processor
    def inject_globals():
        from flask import session
        from app.db import get_db
        cart     = session.get('cart', [])
        wishlist = session.get('wishlist', [])
        settings = get_db().settings.find_one({'_id': 'site'}) or {}
        return {
            'cart_count':    sum(i.get('quantity', 1) for i in cart),
            'wishlist_ids':  wishlist,
            'wishlist_count': len(wishlist),
            'site_logo':     settings.get('site_logo'),
        }

    return app