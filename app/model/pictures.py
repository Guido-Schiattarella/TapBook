"""MODEL — turns the photos coming from the iPad into the file to save.

The controller decides whether and where to insert a photo; here only the data
is transformed: the photo is rotated upright according to the camera
orientation, scaled down (longest side 2000 pixels) and saved as JPEG, or PNG
if it has transparency.
"""
import io
import warnings

from PIL import Image, ImageOps

MAX_IMAGE_SIDE = 2000   # longest side after scaling (pixels)
# "Bomb" images (a few bytes that take gigabytes once decompressed): beyond
# 64 million pixels (8000×8000, more than any iPad camera) they are rejected.
MAX_PIXELS = 64_000_000


def _open(data: bytes) -> Image.Image:
    """Opens the image checking its size BEFORE decompressing it."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.width * img.height > MAX_PIXELS:
                raise InvalidPicture("Immagine troppo grande")
            img.load()
            return img
    except InvalidPicture:
        raise
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError):
        raise InvalidPicture("Il file non è un'immagine valida")


class InvalidPicture(ValueError):
    """The received bytes are not a readable image."""


def prepare_picture(data: bytes) -> tuple[bytes, str, int, int]:
    """Returns (data, extension, width, height)."""
    img = ImageOps.exif_transpose(_open(data))
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img.convert("RGBA").save(out, "PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        ext = "jpg"
    return out.getvalue(), ext, img.width, img.height


AVATAR_SIDE = 320   # profile photo side (pixels)


def prepare_avatar(data: bytes) -> bytes:
    """Profile photo: rotated upright, cropped to the central square and scaled to 320 pixels (JPEG)."""
    img = ImageOps.fit(ImageOps.exif_transpose(_open(data)).convert("RGB"), (AVATAR_SIDE, AVATAR_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()
