import os
from flask import Flask
from .db import init_db


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize database connection
    init_db(app)

    # Register blueprints
    from app.blueprints.admin.auth import admin_auth_bp, admin_bp
    from app.blueprints.admin.products import admin_products_bp
    from app.blueprints.admin.orders import admin_orders_bp
    from app.blueprints.admin.settings import admin_settings_bp
    from app.blueprints.admin.blog import admin_blog_bp
    from app.blueprints.index import index_bp
    from app.blueprints.products import products_bp
    from app.blueprints.pages import pages_bp
    from app.blueprints.blog import blog_bp
    from app.blueprints.cart import cart_bp
    from app.blueprints.checkout import checkout_bp
    from app.blueprints.wishlist import wishlist_bp

    app.register_blueprint(admin_auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_products_bp)
    app.register_blueprint(admin_orders_bp)
    app.register_blueprint(admin_settings_bp)
    app.register_blueprint(admin_blog_bp)
    app.register_blueprint(index_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(wishlist_bp)

    @app.context_processor
    def inject_globals():
        from flask import session
        cart     = session.get('cart', [])
        wishlist = session.get('wishlist', [])
        return {
            'cart_count':    sum(i.get('quantity', 1) for i in cart),
            'wishlist_ids':  wishlist,
            'wishlist_count': len(wishlist),
        }

    return app