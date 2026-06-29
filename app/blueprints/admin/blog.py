import re
from datetime import datetime, timezone
from bson import ObjectId
from flask import (Blueprint, render_template, redirect, request,
                   url_for, flash, session)
from app.uploader import delete_image, upload_image

admin_blog_bp = Blueprint('admin_blog', __name__, url_prefix='/admin/blog')


def _auth_required():
    return session.get('admin_id') is None


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {
        'png', 'jpg', 'jpeg', 'webp', 'gif'
    }


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return re.sub(r'^-+|-+$', '', text)


def _unique_slug(db, base, exclude_id=None):
    slug = base
    n = 1
    while True:
        query = {'slug': slug}
        if exclude_id:
            query['_id'] = {'$ne': exclude_id}
        if not db.posts.find_one(query):
            return slug
        slug = f'{base}-{n}'
        n += 1


@admin_blog_bp.route('/')
def index():
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()
    page = max(1, int(request.args.get('page', 1)))
    per_page = 20

    query = {}
    if status_filter in ('draft', 'published'):
        query['status'] = status_filter
    if search:
        query['$or'] = [
            {'title': {'$regex': search, '$options': 'i'}},
            {'category': {'$regex': search, '$options': 'i'}},
        ]

    total = db.posts.count_documents(query)
    posts = list(
        db.posts.find(query)
                .sort('created_at', -1)
                .skip((page - 1) * per_page)
                .limit(per_page)
    )
    for p in posts:
        p['_id'] = str(p['_id'])

    total_pages = max(1, -(-total // per_page))

    return render_template(
        'admin/blog/index.html',
        posts=posts,
        search=search,
        status_filter=status_filter,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@admin_blog_bp.route('/add', methods=['GET', 'POST'])
def add():
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    if request.method == 'GET':
        return render_template('admin/blog/add.html')

    from app.db import get_db
    db = get_db()

    title = request.form.get('title', '').strip()
    slug_input = request.form.get('slug', '').strip()
    category = request.form.get('category', '').strip()
    excerpt = request.form.get('excerpt', '').strip()
    body = request.form.get('body', '').strip()
    read_time = request.form.get('read_time', '').strip()
    status = request.form.get('status', 'draft')

    if not title:
        flash('Title is required.', 'error')
        return render_template('admin/blog/add.html', form=request.form)

    base_slug = _slugify(slug_input or title)
    slug = _unique_slug(db, base_slug)

    cover_image = None
    file = request.files.get('cover_image')
    if file and file.filename and _allowed(file.filename):
        cover_image = upload_image(file, folder='lepaix/blog')

    now = datetime.now(timezone.utc)
    doc = {
        'title': title,
        'slug': slug,
        'category': category,
        'excerpt': excerpt,
        'body': body,
        'read_time': read_time or '3 min read',
        'cover_image': cover_image,
        'status': status if status in ('draft', 'published') else 'draft',
        'date': now.strftime('%d %b %Y').lstrip('0'),
        'created_at': now,
        'updated_at': now,
    }

    try:
        db.posts.insert_one(doc)
        flash('Post created successfully.', 'success')
        return redirect(url_for('admin_blog.index'))
    except Exception as e:
        flash(f'Error saving post: {e}', 'error')
        return render_template('admin/blog/add.html', form=request.form)


@admin_blog_bp.route('/edit/<post_id>', methods=['GET', 'POST'])
def edit(post_id):
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    try:
        oid = ObjectId(post_id)
    except Exception:
        flash('Invalid post ID.', 'error')
        return redirect(url_for('admin_blog.index'))

    post = db.posts.find_one({'_id': oid})
    if not post:
        flash('Post not found.', 'error')
        return redirect(url_for('admin_blog.index'))
    post['_id'] = str(post['_id'])

    if request.method == 'GET':
        return render_template('admin/blog/edit.html', post=post)

    title = request.form.get('title', '').strip()
    slug_input = request.form.get('slug', '').strip()
    category = request.form.get('category', '').strip()
    excerpt = request.form.get('excerpt', '').strip()
    body = request.form.get('body', '').strip()
    read_time = request.form.get('read_time', '').strip()
    status = request.form.get('status', 'draft')

    if not title:
        flash('Title is required.', 'error')
        return render_template('admin/blog/edit.html', post=post)

    base_slug = _slugify(slug_input or title)
    slug = _unique_slug(db, base_slug, exclude_id=oid)

    cover_image = post.get('cover_image')
    file = request.files.get('cover_image')
    if file and file.filename and _allowed(file.filename):
        delete_image(cover_image)
        cover_image = upload_image(file, folder='lepaix/blog')

    updates = {
        'title': title,
        'slug': slug,
        'category': category,
        'excerpt': excerpt,
        'body': body,
        'read_time': read_time or post.get('read_time', '3 min read'),
        'cover_image': cover_image,
        'status': status if status in ('draft', 'published') else 'draft',
        'updated_at': datetime.now(timezone.utc),
    }

    try:
        db.posts.update_one({'_id': oid}, {'$set': updates})
        flash('Post updated successfully.', 'success')
        return redirect(url_for('admin_blog.index'))
    except Exception as e:
        flash(f'Error updating post: {e}', 'error')
        post.update(updates)
        return render_template('admin/blog/edit.html', post=post)


@admin_blog_bp.route('/delete/<post_id>', methods=['POST'])
def delete(post_id):
    if _auth_required():
        return redirect(url_for('admin_auth.login'))

    from app.db import get_db
    db = get_db()

    try:
        oid = ObjectId(post_id)
    except Exception:
        flash('Invalid post ID.', 'error')
        return redirect(url_for('admin_blog.index'))

    post = db.posts.find_one({'_id': oid}, {'cover_image': 1})
    if post:
        delete_image(post.get('cover_image'))

    db.posts.delete_one({'_id': oid})
    flash('Post deleted.', 'success')
    return redirect(url_for('admin_blog.index'))
