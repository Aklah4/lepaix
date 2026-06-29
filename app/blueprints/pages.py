from flask import Blueprint, render_template

pages_bp = Blueprint('pages', __name__, url_prefix='/pages')


@pages_bp.route('/about')
def about():
    return render_template('pages/about.html')


@pages_bp.route('/contact')
def contact():
    return render_template('pages/contact.html')


@pages_bp.route('/size-guide')
def size_guide():
    return render_template('pages/size_guide.html')


@pages_bp.route('/faq')
def faq():
    return render_template('pages/faq.html')
