import re
from datetime import datetime, timezone

from bson import ObjectId
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from app.db import get_db
from app.sizes import FOOTWEAR_SIZES, LETTER_SIZES, is_footwear, parse_sizes
from app.uploader import delete_image as _delete_image, upload_images
from app.blueprints.admin.categories import ensure_default_categories

admin_products_bp = Blueprint('admin_products', __name__, url_prefix='/admin/products')


def _auth_required():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))
    return None


def _category_names(db):
    ensure_default_categories(db)
    return [c['name'] for c in db.categories.find().sort('order', 1)]


def _allowed(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS'])


def _parse_sale_price(raw, price):
    """Return (sale_price_or_None, error_or_None).

    Blank clears the sale. A value must be a positive number below `price`;
    anything else is rejected so a bad markdown can't slip in silently.
    """
    raw = (raw or '').strip()
    if not raw:
        return None, None
    try:
        sale = float(raw)
    except ValueError:
        return None, 'Sale price must be a number.'
    if sale <= 0:
        return None, 'Sale price must be greater than zero.'
    if price is not None and sale >= price:
        return None, 'Sale price must be lower than the regular price.'
    return sale, None


def _parse_weight(raw):
    """Return (weight_in_grams_or_None, error_or_None).

    Blank is allowed and stays null - delivery falls back to the configured
    default item weight, which is the point of the field being nullable.
    """
    raw = (raw or '').strip()
    if not raw:
        return None, None
    try:
        grams = int(raw)
    except ValueError:
        return None, 'Weight must be a whole number of grams.'
    if grams <= 0:
        return None, 'Weight must be greater than zero grams.'
    return grams, None


def _flash_upload_problems(skipped, failed):
    """Tell the admin which files did not make it, instead of dropping them."""
    if skipped:
        allowed = ', '.join(sorted(current_app.config['ALLOWED_EXTENSIONS']))
        flash(f"Skipped {', '.join(skipped)} - only {allowed} files can be uploaded.",
              'error')
    if failed:
        flash(f"Could not upload {', '.join(failed)} - the image service did not "
              'accept it. The product was saved without it.', 'error')


def _size_ctx(categories, category=None):
    """Both size option sets, and which categories the form treats as footwear.

    The form switches sets as the admin changes category, so it needs to know
    up front which of the options are footwear.
    """
    return {
        'letter_sizes':        LETTER_SIZES,
        'footwear_sizes':      FOOTWEAR_SIZES,
        'footwear_categories': [c for c in categories if is_footwear(c)],
        'footwear_start':      is_footwear(category),
    }


# ── List ──────────────────────────────────────────────────────────────────────
@admin_products_bp.route('/')
def index():
    guard = _auth_required()
    if guard:
        return guard

    db       = get_db()
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = 20
    search   = request.args.get('q', '').strip()
    status   = request.args.get('status', '')
    category = request.args.get('category', '')

    query = {}
    if search:
        query['name'] = {'$regex': re.escape(search), '$options': 'i'}
    if status:
        query['status'] = status
    if category:
        query['category'] = category

    total      = db.products.count_documents(query)
    products   = list(db.products.find(query)
                      .sort('created_at', -1)
                      .skip((page - 1) * per_page)
                      .limit(per_page))
    for p in products:
        p['_id'] = str(p['_id'])

    categories  = db.products.distinct('category')
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('admin/products/index.html',
                           products=products, total=total,
                           page=page, total_pages=total_pages,
                           search=search, selected_status=status,
                           selected_category=category,
                           categories=categories)


# ── Add ───────────────────────────────────────────────────────────────────────
@admin_products_bp.route('/add', methods=['GET', 'POST'])
def add():
    guard = _auth_required()
    if guard:
        return guard

    db         = get_db()
    categories = _category_names(db)

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        price_s  = request.form.get('price', '').strip()
        stock_s  = request.form.get('stock', '0').strip()
        desc     = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        status   = request.form.get('status', 'draft')
        colors   = [c.strip() for c in request.form.get('colors', '').split(',') if c.strip()]
        sizes    = parse_sizes(request.form.getlist('sizes'),
                               request.form.get('sizes_custom', ''))
        featured = request.form.get('featured') == 'on'
        gender   = request.form.get('gender', 'Unisex')

        if not name or not price_s:
            flash('Name and price are required.', 'error')
            return render_template('admin/products/add.html', categories=categories,
                                   **_size_ctx(categories, category))

        try:
            price = float(price_s)
            stock = int(stock_s)
        except ValueError:
            flash('Price and stock must be numbers.', 'error')
            return render_template('admin/products/add.html', categories=categories,
                                   **_size_ctx(categories, category))

        sale_price, sale_err = _parse_sale_price(request.form.get('sale_price'), price)
        if sale_err:
            flash(sale_err, 'error')
            return render_template('admin/products/add.html', categories=categories,
                                   **_size_ctx(categories, category))

        weight_grams, weight_err = _parse_weight(request.form.get('weight_grams'))
        if weight_err:
            flash(weight_err, 'error')
            return render_template('admin/products/add.html', categories=categories,
                                   **_size_ctx(categories, category))

        images, skipped, failed = upload_images(
            request.files.getlist('images'), folder='lepaix/products',
            allowed=current_app.config['ALLOWED_EXTENSIONS'])
        _flash_upload_problems(skipped, failed)

        doc = {
            'name':        name,
            'description': desc,
            'price':       price,
            'sale_price':  sale_price,
            'weight_grams': weight_grams,
            'shipping_class': request.form.get('shipping_class', 'shippable'),
            'stock':       stock,
            'category':    category,
            'status':      status,
            'colors':      colors,
            'sizes':       sizes,
            'images':      images,
            'featured':    featured,
            'gender':      gender,
            'created_at':  datetime.now(timezone.utc),
        }

        try:
            db.products.insert_one(doc)
        except Exception as e:
            flash(f'Database error: {e}', 'error')
            return render_template('admin/products/add.html', categories=categories,
                                   **_size_ctx(categories, category))

        flash(f'Product "{name}" added successfully.', 'success')
        return redirect(url_for('admin_products.index'))

    return render_template('admin/products/add.html', categories=categories, **_size_ctx(categories))


# ── Edit ──────────────────────────────────────────────────────────────────────
@admin_products_bp.route('/<product_id>/edit', methods=['GET', 'POST'])
def edit(product_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(product_id)
    except Exception:
        flash('Invalid product ID.', 'error')
        return redirect(url_for('admin_products.index'))

    product = db.products.find_one({'_id': oid})
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('admin_products.index'))

    product['_id'] = str(product['_id'])
    categories = _category_names(db)
    if product.get('category') and product['category'] not in categories:
        categories = [product['category']] + categories

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        price_s  = request.form.get('price', '').strip()
        stock_s  = request.form.get('stock', '0').strip()
        desc     = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        status   = request.form.get('status', 'draft')
        colors   = [c.strip() for c in request.form.get('colors', '').split(',') if c.strip()]
        sizes    = parse_sizes(request.form.getlist('sizes'),
                               request.form.get('sizes_custom', ''))
        featured = request.form.get('featured') == 'on'
        gender   = request.form.get('gender', 'Unisex')

        if not name or not price_s:
            flash('Name and price are required.', 'error')
            return render_template('admin/products/edit.html', product=product,
                                   categories=categories, **_size_ctx(categories, category))

        try:
            price = float(price_s)
            stock = int(stock_s)
        except ValueError:
            flash('Price and stock must be numbers.', 'error')
            return render_template('admin/products/edit.html', product=product,
                                   categories=categories, **_size_ctx(categories, category))

        sale_price, sale_err = _parse_sale_price(request.form.get('sale_price'), price)
        if sale_err:
            flash(sale_err, 'error')
            return render_template('admin/products/edit.html', product=product,
                                   categories=categories, **_size_ctx(categories, category))

        weight_grams, weight_err = _parse_weight(request.form.get('weight_grams'))
        if weight_err:
            flash(weight_err, 'error')
            return render_template('admin/products/edit.html', product=product,
                                   categories=categories, **_size_ctx(categories, category))

        # Append newly uploaded images to existing ones
        existing_images = product.get('images', [])
        new_images, skipped, failed = upload_images(
            request.files.getlist('images'), folder='lepaix/products',
            allowed=current_app.config['ALLOWED_EXTENSIONS'])
        existing_images.extend(new_images)
        _flash_upload_problems(skipped, failed)

        try:
            db.products.update_one({'_id': oid}, {'$set': {
                'name':        name,
                'description': desc,
                'price':       price,
                'sale_price':  sale_price,
                'weight_grams': weight_grams,
                'shipping_class': request.form.get('shipping_class', 'shippable'),
                'stock':       stock,
                'category':    category,
                'status':      status,
                'colors':      colors,
                'sizes':       sizes,
                'images':      existing_images,
                'featured':    featured,
                'gender':      gender,
                'updated_at':  datetime.now(timezone.utc),
            }})
        except Exception as e:
            flash(f'Database error: {e}', 'error')
            return render_template('admin/products/edit.html', product=product,
                                   categories=categories, **_size_ctx(categories, category))

        flash(f'Product "{name}" updated.', 'success')
        return redirect(url_for('admin_products.index'))

    return render_template('admin/products/edit.html', product=product, categories=categories,
                           **_size_ctx(categories, product.get('category')))


# ── Delete ────────────────────────────────────────────────────────────────────
@admin_products_bp.route('/<product_id>/delete', methods=['POST'])
def delete(product_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(product_id)
    except Exception:
        flash('Invalid product ID.', 'error')
        return redirect(url_for('admin_products.index'))

    product = db.products.find_one({'_id': oid})
    if product:
        for img in product.get('images', []):
            _delete_image(img)
        db.products.delete_one({'_id': oid})
        flash(f'Product "{product.get("name","")}" deleted.', 'success')

    return redirect(url_for('admin_products.index'))


# ── Delete single image ───────────────────────────────────────────────────────
@admin_products_bp.route('/<product_id>/images/delete', methods=['POST'])
def delete_image(product_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(product_id)
    except Exception:
        return redirect(url_for('admin_products.index'))

    image = request.form.get('image', '').strip()
    if image:
        product = db.products.find_one({'_id': oid})
        images = list(product.get('images', [])) if product else []
        if image in images:
            # Remove only a single occurrence — never every matching entry —
            # so deleting one image can't wipe the whole gallery.
            images.remove(image)
            db.products.update_one({'_id': oid}, {'$set': {'images': images}})
            # Only destroy the Cloudinary asset if no other entry still uses it.
            if image not in images:
                _delete_image(image)
            flash('Image removed.', 'success')

    return redirect(url_for('admin_products.edit', product_id=product_id))
