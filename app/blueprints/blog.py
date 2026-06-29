from flask import Blueprint, render_template, abort
from app.db import get_db

blog_bp = Blueprint('blog', __name__, url_prefix='/blog')

_DEMO_POSTS = [
    {
        '_id': str(i), 'slug': f'post-{i}',
        'title': title, 'category': cat, 'date': '15 May 2026',
        'excerpt': 'Discover the latest trends and styling tips from our editorial team.',
        'read_time': '4 min read',
        'bg': bg,
    }
    for i, (title, cat, bg) in enumerate([
        ('The Art of Layering for Autumn', 'Style Guide', '#c4843c'),
        ('Essential Pieces for a Minimal Wardrobe', 'Fashion', '#e8b8c0'),
        ('Behind the Collection: SS26', 'Editorial', '#b8c8d8'),
        ('How to Style Neutral Tones', 'Style Guide', '#c8c0a0'),
        ('Sustainable Fabrics We Love', 'Sustainability', '#e0d4b0'),
        ('Spring Colour Palette Breakdown', 'Trend Report', '#9098a8'),
    ])
]


@blog_bp.route('/')
def index():
    db    = get_db()
    raw   = list(db.posts.find().sort('created_at', -1).limit(9))
    for p in raw:
        p['_id'] = str(p['_id'])

    posts = raw if raw else _DEMO_POSTS
    return render_template('blog/index.html', posts=posts)


@blog_bp.route('/<slug>')
def post(slug):
    db   = get_db()
    item = db.posts.find_one({'slug': slug})

    if item:
        item['_id'] = str(item['_id'])
        recent = list(db.posts.find({'slug': {'$ne': slug}}).sort('created_at', -1).limit(3))
        for p in recent:
            p['_id'] = str(p['_id'])
    else:
        # fall back to demo
        item   = next((p for p in _DEMO_POSTS if p['slug'] == slug), None)
        recent = [p for p in _DEMO_POSTS if p['slug'] != slug][:3]

    if not item:
        abort(404)

    return render_template('blog/post.html', post=item, recent=recent)
