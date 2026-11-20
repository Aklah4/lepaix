import os
import uuid

import cloudinary
import cloudinary.uploader
from flask import current_app
from werkzeug.utils import secure_filename


def upload_image(file, folder='lepaix'):
    """Upload to Cloudinary, falling back to the app's configured upload folder.

    The filesystem fallback keeps admin uploads usable when Cloudinary is not
    configured or temporarily unavailable. A unique, sanitized filename keeps
    user supplied paths out of the upload directory and avoids collisions.
    """
    cloudinary_keys = (
        current_app.config.get('CLOUDINARY_CLOUD_NAME'),
        current_app.config.get('CLOUDINARY_API_KEY'),
        current_app.config.get('CLOUDINARY_API_SECRET'),
    )
    if all(cloudinary_keys):
        try:
            result = cloudinary.uploader.upload(file, folder=folder)
            return result['secure_url']
        except Exception:
            current_app.logger.exception(
                'Cloudinary upload failed; saving %r locally',
                getattr(file, 'filename', file),
            )
            file.stream.seek(0)

    filename = secure_filename(getattr(file, 'filename', '') or '')
    if not filename or '.' not in filename:
        raise ValueError('The uploaded image must have a filename and extension.')
    extension = filename.rsplit('.', 1)[1].lower()
    stored_name = f'{uuid.uuid4().hex}.{extension}'
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    file.save(os.path.join(upload_folder, stored_name))
    return stored_name


def upload_image_safe(file, folder='lepaix'):
    """Upload, returning None instead of raising when both storage paths fail.

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
    and local storage could not save. Never raises, so a bad file can't lose
    the whole form.
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
        try:
            cloudinary.uploader.destroy(public_id)
        except Exception:
            current_app.logger.exception('Cloudinary image deletion failed')
        return

    # Local uploads are stored as generated filenames, never as user paths.
    if url and not url.startswith('http'):
        filename = os.path.basename(url)
        if filename == url:
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                current_app.logger.exception('Local image deletion failed for %r', filename)


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
