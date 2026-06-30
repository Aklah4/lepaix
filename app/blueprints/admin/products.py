from datetime import datetime, timezone

from bson import ObjectId
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from app.db import get_db
from app.uploader import delete_image as _delete_image, upload_image

admin_products_bp = Blueprint('admin_products', __name__, url_prefix='/admin/products')


def _auth_required():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))
    return None


def _allowed(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS'])


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
        query['name'] = {'$regex': search, '$options': 'i'}
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

    db = get_db()

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        price_s  = request.form.get('price', '').strip()
        stock_s  = request.form.get('stock', '0').strip()
        desc     = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        status   = request.form.get('status', 'draft')
        colors   = [c.strip() for c in request.form.get('colors', '').split(',') if c.strip()]
        sizes    = request.form.getlist('sizes')
        featured = request.form.get('featured') == 'on'
        gender   = request.form.get('gender', 'Unisex')

        if not name or not price_s:
            flash('Name and price are required.', 'error')
            return render_template('admin/products/add.html')

        try:
            price = float(price_s)
            stock = int(stock_s)
        except ValueError:
            flash('Price and stock must be numbers.', 'error')
            return render_template('admin/products/add.html')

        images = []
        for file in request.files.getlist('images'):
            if file and file.filename and _allowed(file.filename):
                images.append(upload_image(file, folder='lepaix/products'))

        doc = {
            'name':        name,
            'description': desc,
            'price':       price,
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
            return render_template('admin/products/add.html')

        flash(f'Product "{name}" added successfully.', 'success')
        return redirect(url_for('admin_products.index'))

    return render_template('admin/products/add.html')


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

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        price_s  = request.form.get('price', '').strip()
        stock_s  = request.form.get('stock', '0').strip()
        desc     = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        status   = request.form.get('status', 'draft')
        colors   = [c.strip() for c in request.form.get('colors', '').split(',') if c.strip()]
        sizes    = request.form.getlist('sizes')
        featured = request.form.get('featured') == 'on'
        gender   = request.form.get('gender', 'Unisex')

        if not name or not price_s:
            flash('Name and price are required.', 'error')
            return render_template('admin/products/edit.html', product=product)

        try:
            price = float(price_s)
            stock = int(stock_s)
        except ValueError:
            flash('Price and stock must be numbers.', 'error')
            return render_template('admin/products/edit.html', product=product)

        # Append newly uploaded images to existing ones
        existing_images = product.get('images', [])
        for file in request.files.getlist('images'):
            if file and file.filename and _allowed(file.filename):
                existing_images.append(upload_image(file, folder='lepaix/products'))

        try:
            db.products.update_one({'_id': oid}, {'$set': {
                'name':        name,
                'description': desc,
                'price':       price,
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
            return render_template('admin/products/edit.html', product=product)

        flash(f'Product "{name}" updated.', 'success')
        return redirect(url_for('admin_products.index'))

    return render_template('admin/products/edit.html', product=product)


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
@admin_products_bp.route('/<product_id>/images/<filename>/delete', methods=['POST'])
def delete_image(product_id, filename):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(product_id)
    except Exception:
        return redirect(url_for('admin_products.index'))

    db.products.update_one({'_id': oid}, {'$pull': {'images': filename}})
    _delete_image(filename)

    return redirect(url_for('admin_products.edit', product_id=product_id))
