from bson import ObjectId
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.db import get_db
from app.uploader import delete_image, upload_image

admin_categories_bp = Blueprint('admin_categories', __name__, url_prefix='/admin/categories')

DEFAULT_CATEGORIES = [
    {'name': 'Men',           'link': '/products?gender=Men',              'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Men',             'order': 1},
    {'name': 'Women',         'link': '/products?gender=Women',            'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Women',           'order': 2},
    {'name': 'Bags',          'link': '/products?category=Bags',           'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Bags',            'order': 3},
    {'name': "Men's Shoes",   'link': '/products?category=Men%27s+Shoes',  'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Men%27s+Shoes',   'order': 4},
    {'name': "Women's Shoes", 'link': '/products?category=Women%27s+Shoes','image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Women%27s+Shoes', 'order': 5},
    {'name': 'Accessories',   'link': '/products?category=Accessories',    'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Accessories',     'order': 6},
    {'name': 'Glasses',       'link': '/products?category=Glasses',        'image': 'https://placehold.co/300x400/e8e4df/9e9e9a?text=Glasses',         'order': 7},
]


def ensure_default_categories(db):
    """Seed the categories collection once so the homepage grid always has content."""
    if db.categories.count_documents({}) == 0:
        db.categories.insert_many([dict(c) for c in DEFAULT_CATEGORIES])


def _auth_required():
    if not session.get('admin_id'):
        return redirect(url_for('admin_auth.login'))
    return None


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'webp', 'gif'}


@admin_categories_bp.route('/')
def index():
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    ensure_default_categories(db)
    categories = list(db.categories.find().sort('order', 1))
    for c in categories:
        c['_id'] = str(c['_id'])

    return render_template('admin/categories/index.html', categories=categories)


@admin_categories_bp.route('/add', methods=['GET', 'POST'])
def add():
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()

    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        link    = request.form.get('link', '').strip() or '/products'
        order_s = request.form.get('order', '').strip()

        if not name:
            flash('Category name is required.', 'error')
            return render_template('admin/categories/add.html')

        try:
            order = int(order_s) if order_s else db.categories.count_documents({}) + 1
        except ValueError:
            order = db.categories.count_documents({}) + 1

        image = ''
        file = request.files.get('image')
        if file and file.filename and _allowed(file.filename):
            image = upload_image(file, folder='lepaix/categories')

        db.categories.insert_one({
            'name':  name,
            'link':  link,
            'image': image,
            'order': order,
        })
        flash(f'Category "{name}" added.', 'success')
        return redirect(url_for('admin_categories.index'))

    return render_template('admin/categories/add.html')


@admin_categories_bp.route('/<category_id>/edit', methods=['GET', 'POST'])
def edit(category_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(category_id)
    except Exception:
        flash('Invalid category ID.', 'error')
        return redirect(url_for('admin_categories.index'))

    category = db.categories.find_one({'_id': oid})
    if not category:
        flash('Category not found.', 'error')
        return redirect(url_for('admin_categories.index'))
    category['_id'] = str(category['_id'])

    products_in_category = list(db.products.find({'category': category['name']}).sort('name', 1))
    for p in products_in_category:
        p['_id'] = str(p['_id'])

    available_products = list(db.products.find({'category': {'$ne': category['name']}}).sort('name', 1))
    for p in available_products:
        p['_id'] = str(p['_id'])

    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        link    = request.form.get('link', '').strip() or '/products'
        order_s = request.form.get('order', '').strip()

        if not name:
            flash('Category name is required.', 'error')
            return render_template('admin/categories/edit.html', category=category,
                                   products_in_category=products_in_category,
                                   available_products=available_products)

        try:
            order = int(order_s) if order_s else category.get('order', 0)
        except ValueError:
            order = category.get('order', 0)

        image = category.get('image', '')
        file = request.files.get('image')
        if file and file.filename and _allowed(file.filename):
            delete_image(image)
            image = upload_image(file, folder='lepaix/categories')

        db.categories.update_one({'_id': oid}, {'$set': {
            'name':  name,
            'link':  link,
            'image': image,
            'order': order,
        }})

        old_name = category.get('name', '')
        if old_name and old_name != name:
            db.products.update_many({'category': old_name}, {'$set': {'category': name}})

        flash(f'Category "{name}" updated.', 'success')
        return redirect(url_for('admin_categories.index'))

    return render_template('admin/categories/edit.html', category=category,
                           products_in_category=products_in_category,
                           available_products=available_products)


@admin_categories_bp.route('/<category_id>/products/add', methods=['POST'])
def add_product(category_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(category_id)
    except Exception:
        flash('Invalid category ID.', 'error')
        return redirect(url_for('admin_categories.index'))

    category = db.categories.find_one({'_id': oid})
    if not category:
        flash('Category not found.', 'error')
        return redirect(url_for('admin_categories.index'))

    try:
        product_oid = ObjectId(request.form.get('product_id', '').strip())
    except Exception:
        flash('Please choose a product to add.', 'error')
        return redirect(url_for('admin_categories.edit', category_id=category_id))

    result = db.products.update_one({'_id': product_oid}, {'$set': {'category': category['name']}})
    if result.matched_count:
        flash('Product added to category.', 'success')
    else:
        flash('Product not found.', 'error')

    return redirect(url_for('admin_categories.edit', category_id=category_id))


@admin_categories_bp.route('/<category_id>/products/<product_id>/remove', methods=['POST'])
def remove_product(category_id, product_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        product_oid = ObjectId(product_id)
    except Exception:
        flash('Invalid product.', 'error')
        return redirect(url_for('admin_categories.edit', category_id=category_id))

    db.products.update_one({'_id': product_oid}, {'$set': {'category': ''}})
    flash('Product removed from category.', 'success')
    return redirect(url_for('admin_categories.edit', category_id=category_id))


@admin_categories_bp.route('/<category_id>/delete', methods=['POST'])
def delete(category_id):
    guard = _auth_required()
    if guard:
        return guard

    db = get_db()
    try:
        oid = ObjectId(category_id)
    except Exception:
        flash('Invalid category ID.', 'error')
        return redirect(url_for('admin_categories.index'))

    category = db.categories.find_one({'_id': oid})
    if category:
        delete_image(category.get('image'))
        db.categories.delete_one({'_id': oid})
        flash(f'Category "{category.get("name", "")}" deleted.', 'success')

    return redirect(url_for('admin_categories.index'))
