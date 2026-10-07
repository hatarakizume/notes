import base64
import binascii
import io
import re
import warnings

from PIL import Image, UnidentifiedImageError

DRAWING_PREFIX = "data:image/png;base64,"
MAX_DRAWING_LEN = 2 * 1024 * 1024
MAX_DRAWING_SIDE = 4096
MAX_DRAWING_PIXELS = MAX_DRAWING_SIDE * MAX_DRAWING_SIDE

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BASE64_RE = re.compile(r"\A[A-Za-z0-9+/]*={0,2}\Z")


class DrawingError(ValueError):
    pass


def validate_drawing(value):
    if value == "":
        return value
    if len(value) > MAX_DRAWING_LEN:
        raise DrawingError("Рисунок слишком большой")
    if not value.startswith(DRAWING_PREFIX):
        raise DrawingError("Рисунок должен быть PNG в формате data URL")

    payload = value[len(DRAWING_PREFIX) :]
    if not payload or len(payload) % 4 or not _BASE64_RE.match(payload):
        raise DrawingError("Некорректные данные base64 в рисунке")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise DrawingError("Некорректные данные base64 в рисунке")
    if not raw.startswith(PNG_SIGNATURE):
        raise DrawingError("Рисунок должен быть PNG в формате data URL")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format != "PNG":
                    raise DrawingError("Рисунок должен быть PNG в формате data URL")
                probe.verify()
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != "PNG":
                    raise DrawingError("Рисунок должен быть PNG в формате data URL")
                width, height = img.size
                if (
                    width > MAX_DRAWING_SIDE
                    or height > MAX_DRAWING_SIDE
                    or width * height > MAX_DRAWING_PIXELS
                ):
                    raise DrawingError(
                        f"Размер рисунка не должен превышать "
                        f"{MAX_DRAWING_SIDE}x{MAX_DRAWING_SIDE} пикселей"
                    )
                img.load()
    except DrawingError:
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
        raise DrawingError("Рисунок повреждён или не является PNG")
    return value
