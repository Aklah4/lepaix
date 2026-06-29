from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from models import db, Product, Order, Customer, OrderItem
from sqlalchemy import func
from datetime import datetime, timedelta

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.route('/')
@login_required
def index():
    stats = get_stats()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    low_stock = Product.query.filter(Product.stock < 10).order_by(Product.stock).limit(5).all()
    return render_template('dashboard/index.html',
                           stats=stats,
                           recent_orders=recent_orders,
                           low_stock=low_stock)


@dashboard_bp.route('/stats')
@login_required
def stats():
    return jsonify(get_stats())


def get_stats():
    total_products = Product.query.count()
    total_orders = Order.query.count()
    total_customers = Customer.query.count()

    total_revenue = db.session.query(func.sum(Order.total_amount)).scalar() or 0

    # Revenue last 7 days
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_revenue = db.session.query(func.sum(Order.total_amount))\
        .filter(Order.created_at >= seven_days_ago).scalar() or 0

    # Orders by status
    orders_by_status = db.session.query(Order.status, func.count(Order.id))\
        .group_by(Order.status).all()

    # Top products
    top_products = db.session.query(
        Product.name,
        func.sum(OrderItem.quantity).label('total_sold')
    ).join(OrderItem).group_by(Product.id)\
     .order_by(func.sum(OrderItem.quantity).desc()).limit(5).all()

    # Monthly revenue for chart (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = datetime.utcnow().replace(day=1) - timedelta(days=30 * i)
        month_end = month_start + timedelta(days=31)
        revenue = db.session.query(func.sum(Order.total_amount))\
            .filter(Order.created_at >= month_start, Order.created_at < month_end).scalar() or 0
        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'revenue': round(revenue, 2)
        })

    return {
        'total_products': total_products,
        'total_orders': total_orders,
        'total_customers': total_customers,
        'total_revenue': round(total_revenue, 2),
        'recent_revenue': round(recent_revenue, 2),
        'orders_by_status': dict(orders_by_status),
        'top_products': [{'name': p[0], 'sold': p[1]} for p in top_products],
        'monthly_revenue': monthly_data
    }
