import cloudinary
import cloudinary.uploader


def upload_image(file, folder='lepaix'):
    result = cloudinary.uploader.upload(file, folder=folder)
    return result['secure_url']


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
