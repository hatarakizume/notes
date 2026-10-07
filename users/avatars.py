import io
import os
import uuid
import warnings

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_SIDE = 2048
MAX_AVATAR_PIXELS = MAX_AVATAR_SIDE * MAX_AVATAR_SIDE

ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

AVATAR_DIR = "avatars"


def _error(message, code):
    return ValidationError(message, code=code)


def _open_and_check(file_obj):
    size = getattr(file_obj, "size", None)
    if size is None or size > MAX_AVATAR_BYTES:
        raise _error("Файл аватарки больше 2 МБ.", "file_too_large")
    if size == 0:
        raise _error("Файл аватарки пуст.", "empty")

    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(file_obj)
            if img.format not in ALLOWED_FORMATS:
                raise _error(
                    "Допустимы только изображения JPEG и PNG.", "invalid_format"
                )
            width, height = img.size
            if (
                width < 1
                or height < 1
                or width > MAX_AVATAR_SIDE
                or height > MAX_AVATAR_SIDE
                or width * height > MAX_AVATAR_PIXELS
            ):
                raise _error(
                    f"Размер изображения не должен превышать "
                    f"{MAX_AVATAR_SIDE}x{MAX_AVATAR_SIDE} пикселей.",
                    "invalid_dimensions",
                )
            img.load()
    except ValidationError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
    ):
        raise _error(
            "Файл не является корректным изображением JPEG или PNG.",
            "invalid_image",
        )
    finally:
        try:
            file_obj.seek(0)
        except (AttributeError, OSError):
            pass
    return img


def validate_avatar_file(file_obj):
    name = getattr(file_obj, "name", "") or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise _error("Допустимы только файлы .jpg, .jpeg и .png.", "invalid_extension")
    img = _open_and_check(file_obj)
    img.close()


def process_avatar(file_obj):
    img = _open_and_check(file_obj)
    try:
        fmt = img.format
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        if fmt == "JPEG":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
        else:
            if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                img = img.convert("RGBA")

        out = io.BytesIO()
        if fmt == "JPEG":
            img.save(out, format="JPEG", quality=90, optimize=True)
        else:
            img.save(out, format="PNG", optimize=True)
    except (OSError, ValueError):
        raise _error(
            "Файл не является корректным изображением JPEG или PNG.", "invalid_image"
        )
    finally:
        img.close()

    data = out.getvalue()
    if len(data) > MAX_AVATAR_BYTES:
        raise _error("Файл аватарки больше 2 МБ.", "file_too_large")
    return ContentFile(data, name=f"{uuid.uuid4().hex}.{ALLOWED_FORMATS[fmt]}")


def avatar_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in ALLOWED_EXTENSIONS:
        ext = ""
    return f"{AVATAR_DIR}/{uuid.uuid4().hex}{ext}"
