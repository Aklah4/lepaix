import cloudinary
import cloudinary.uploader
from flask import current_app


def upload_image(file, folder='lepaix'):
    result = cloudinary.uploader.upload(file, folder=folder)
    return result['secure_url']


def upload_image_safe(file, folder='lepaix'):
    """Upload, returning None instead of raising when Cloudinary is unhappy.

    Lets a save go through without its image rather than 500ing and throwing
    away everything the admin typed.
    """
    try:
        return upload_image(file, folder=folder)
    except Exception:
        current_app.logger.exception('Cloudinary upload failed for %r',
                                     getattr(file, 'filename', file))
        return None


def upload_images(files, folder='lepaix', allowed=None):
    """Upload a batch. Returns (urls, skipped_names, failed_names).

    `skipped` are files rejected by extension, `failed` are ones Cloudinary
    refused. Never raises, so a bad file can't lose the whole form.
    """
    urls, skipped, failed = [], [], []
    for file in files:
        if not file or not file.filename:
            continue
        if allowed and not _has_allowed_ext(file.filename, allowed):
            skipped.append(file.filename)
            continue
        url = upload_image_safe(file, folder=folder)
        if url:
            urls.append(url)
        else:
            failed.append(file.filename)
    return urls, skipped, failed


def _has_allowed_ext(filename, allowed):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def delete_image(url):
    public_id = _extract_public_id(url)
    if public_id:
        cloudinary.uploader.destroy(public_id)


def _extract_public_id(url):
    if not url or not url.startswith('http'):
        return None
    parts = url.split('/upload/', 1)
    if len(parts) != 2:
        return None
    path = parts[1]
    # Strip version prefix like v1234567890/
    if path.startswith('v') and '/' in path:
        first, rest = path.split('/', 1)
        if first[1:].isdigit():
            path = rest
    return path.rsplit('.', 1)[0]
