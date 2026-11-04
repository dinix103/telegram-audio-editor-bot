import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from .files import UserError

Image.MAX_IMAGE_PIXELS = 20_000_000


def normalize_cover(source: Path | bytes, destination: Path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source) if isinstance(source, bytes) else source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1400, 1400))
                image.convert("RGB").save(destination, "JPEG", quality=90)
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UserError("Обложка повреждена или слишком большая. Отправьте JPEG/PNG.") from None
