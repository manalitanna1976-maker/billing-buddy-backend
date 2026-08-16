import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Magic-byte signatures — the extension alone doesn't prove the content is
# actually an image; a relabeled arbitrary file would otherwise be accepted
# and served back to browsers from /uploads/...
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def _looks_like_image(ext: str, content: bytes) -> bool:
    if ext == ".png":
        return content.startswith(_PNG_SIGNATURE)
    if ext in (".jpg", ".jpeg"):
        return content.startswith(_JPEG_SIGNATURE)
    return False


def save_upload(business_id: uuid.UUID, kind: str, filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    if not _looks_like_image(ext, content):
        raise ValueError("File content does not match a supported image format")

    business_dir = Path(settings.upload_dir) / str(business_id)
    business_dir.mkdir(parents=True, exist_ok=True)

    dest = business_dir / f"{kind}{ext}"
    dest.write_bytes(content)

    return f"/uploads/{business_id}/{kind}{ext}"
