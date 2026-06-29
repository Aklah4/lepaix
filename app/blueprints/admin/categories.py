from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from models import db, Category
import re

categories_bp = Blueprint('categories', __name__, url_prefix='/categories')


def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


@categories_bp.route('/')
@login_required
def index():
    categories = Category.query.order_by(Category.name).all()
    return render_template('categories/index.html', categories=categories)


@categories_bp.route('/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Category name is required.', 'error')
        return redirect(url_for('categories.index'))

    slug = slugify(name)
    if Category.query.filter_by(slug=slug).first():
        flash('Category already exists.', 'error')
        return redirect(url_for('categories.index'))

    category = Category(name=name, slug=slug)
    db.session.add(category)
    db.session.commit()
    flash(f'Category "{name}" added.', 'success')
    return redirect(url_for('categories.index'))


@categories_bp.route('/<int:category_id>/delete', methods=['POST'])
@login_required
def delete(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash(f'Category "{category.name}" deleted.', 'success')
    return redirect(url_for('categories.index'))
