"""Photo ingest: turn whatever was uploaded into something the display can show.

One pipeline, used by the upload endpoint and by the directory scan, so a
photo dropped straight into the photos folder is treated exactly like one
uploaded from a phone:

1. Apply the EXIF orientation (``exif_transpose``). Phones store portrait
   shots as landscape pixels plus a rotation tag; browsers honour the tag
   for ``<img>`` but the old code dropped it on re-save, so photos rendered
   sideways.
2. Convert to RGB (drops alpha, CMYK, HEIC colour spaces).
3. Resize to fit within ``max_dimension`` on the long edge. A wall display
   does not need 24 megapixels, and decoding an 8 MB JPEG on a Pi is what
   made the crossfade stutter.
4. Save as a progressive JPEG in ``photos/processed/<stem>.jpg`` and return
   the dimensions, so the frontend can choose cover vs. contain per photo.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - Pillow is a hard dependency
    PIL_AVAILABLE = False

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - optional
    HEIF_AVAILABLE = False

PROCESSED_DIRNAME = "processed"
DEFAULT_MAX_DIMENSION = 2048
JPEG_QUALITY = 86

ORIGINAL_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif")


@dataclass(frozen=True)
class ProcessedPhoto:
    filename: str  # basename inside the processed directory
    width: int
    height: int

    @property
    def orientation(self) -> str:
        if self.width > self.height * 1.05:
            return "landscape"
        if self.height > self.width * 1.05:
            return "portrait"
        return "square"


def processed_dir(photos_dir: str | os.PathLike) -> Path:
    return Path(photos_dir) / PROCESSED_DIRNAME


def processed_name(original_filename: str) -> str:
    return Path(original_filename).stem + ".jpg"


def is_original(filename: str) -> bool:
    return filename.lower().endswith(ORIGINAL_EXTENSIONS)


def process_photo(
    original_path: str | os.PathLike,
    photos_dir: str | os.PathLike,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
) -> Optional[ProcessedPhoto]:
    """Produce the display variant for one original. Returns None on failure."""
    if not PIL_AVAILABLE:  # pragma: no cover
        logger.error("Pillow is not installed; cannot process photos")
        return None

    original_path = Path(original_path)
    out_dir = processed_dir(photos_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / processed_name(original_path.name)
    tmp_path = out_path.with_suffix(".tmp.jpg")

    try:
        with Image.open(original_path) as source:
            img: Image.Image = ImageOps.exif_transpose(source) or source
            if img.mode != "RGB":
                img = img.convert("RGB")
            if max_dimension and max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            width, height = img.size
            img.save(
                tmp_path,
                "JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        os.replace(tmp_path, out_path)
    except Exception as e:
        logger.error("Could not process photo %s: %s", original_path.name, e)
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return None

    logger.info(
        "Processed %s -> %s (%dx%d)", original_path.name, out_path.name, width, height
    )
    return ProcessedPhoto(filename=out_path.name, width=width, height=height)


def remove_processed(original_filename: str, photos_dir: str | os.PathLike) -> None:
    path = processed_dir(photos_dir) / processed_name(original_filename)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)
