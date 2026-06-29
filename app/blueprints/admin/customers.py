from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from models import db, Customer

customers_bp = Blueprint('customers', __name__, url_prefix='/customers')


@customers_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '')
    query = Customer.query
    if search:
        query = query.filter(
            Customer.name.ilike(f'%{search}%') | Customer.email.ilike(f'%{search}%')
        )
    customers = query.order_by(Customer.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('customers/index.html', customers=customers, search=search)


@customers_bp.route('/<int:customer_id>')
@login_required
def detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    return render_template('customers/detail.html', customer=customer)


@customers_bp.route('/<int:customer_id>/delete', methods=['POST'])
@login_required
def delete(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    flash(f'Customer "{customer.name}" removed.', 'success')
    return redirect(url_for('customers.index'))
