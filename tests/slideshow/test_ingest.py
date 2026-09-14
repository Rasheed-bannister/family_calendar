"""Tests for src/slideshow/ingest.py, using real images made with Pillow."""

from pathlib import Path

import pytest
from PIL import Image

from src.slideshow import ingest


def make_image(path: Path, size=(40, 20), mode="RGB", fmt=None, orientation=None):
    img = Image.new(mode, size, color=(200, 30, 30) if mode != "L" else 128)
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif.tobytes()
    img.save(path, fmt, **kwargs)
    return path


class TestHelpers:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.jpg", True),
            ("b.JPEG", True),
            ("c.heic", True),
            ("d.webp", True),
            ("e.txt", False),
            ("f.jpg.bak", False),
        ],
    )
    def test_is_original(self, name, expected):
        assert ingest.is_original(name) is expected

    def test_processed_name_and_dir(self, tmp_path):
        assert ingest.processed_name("IMG_1.HEIC") == "IMG_1.jpg"
        assert ingest.processed_dir(tmp_path) == tmp_path / "processed"

    @pytest.mark.parametrize(
        "w,h,expected",
        [
            (40, 20, "landscape"),
            (20, 40, "portrait"),
            (30, 30, "square"),
            (31, 30, "square"),
        ],
    )
    def test_orientation(self, w, h, expected):
        assert ingest.ProcessedPhoto("x.jpg", w, h).orientation == expected


class TestProcessPhoto:
    def test_writes_a_jpeg_variant_with_dimensions(self, tmp_path):
        src = make_image(tmp_path / "photo.png", size=(40, 20))
        result = ingest.process_photo(src, tmp_path)
        assert result == ingest.ProcessedPhoto("photo.jpg", 40, 20)
        out = tmp_path / "processed" / "photo.jpg"
        with Image.open(out) as img:
            assert img.format == "JPEG"
            assert img.size == (40, 20)
            assert img.mode == "RGB"
        assert not list((tmp_path / "processed").glob("*.tmp.jpg"))

    def test_resizes_to_the_long_edge(self, tmp_path):
        src = make_image(tmp_path / "big.jpg", size=(200, 100))
        result = ingest.process_photo(src, tmp_path, max_dimension=50)
        assert (result.width, result.height) == (50, 25)

    def test_small_images_are_not_upscaled(self, tmp_path):
        src = make_image(tmp_path / "small.jpg", size=(20, 10))
        result = ingest.process_photo(src, tmp_path, max_dimension=2048)
        assert (result.width, result.height) == (20, 10)

    def test_exif_orientation_is_baked_in(self, tmp_path):
        """A landscape file tagged 'rotate 90' must come out portrait."""
        src = make_image(tmp_path / "rotated.jpg", size=(40, 20), orientation=6)
        result = ingest.process_photo(src, tmp_path)
        assert (result.width, result.height) == (20, 40)
        assert result.orientation == "portrait"
        with Image.open(tmp_path / "processed" / "rotated.jpg") as img:
            assert img.getexif().get(0x0112) in (None, 1)

    def test_alpha_and_greyscale_are_converted_to_rgb(self, tmp_path):
        for name, mode in (("rgba.png", "RGBA"), ("grey.png", "L")):
            src = make_image(tmp_path / name, mode=mode)
            ingest.process_photo(src, tmp_path)
            with Image.open(
                tmp_path / "processed" / name.replace(".png", ".jpg")
            ) as img:
                assert img.mode == "RGB"

    def test_corrupt_file_returns_none_and_leaves_no_debris(self, tmp_path, caplog):
        src = tmp_path / "broken.jpg"
        src.write_bytes(b"not an image")
        with caplog.at_level("ERROR"):
            assert ingest.process_photo(src, tmp_path) is None
        assert "Could not process photo broken.jpg" in caplog.text
        processed = tmp_path / "processed"
        assert not processed.exists() or list(processed.iterdir()) == []

    def test_reprocessing_replaces_atomically(self, tmp_path):
        src = make_image(tmp_path / "p.jpg", size=(40, 20))
        ingest.process_photo(src, tmp_path)
        make_image(src, size=(60, 30))
        result = ingest.process_photo(src, tmp_path)
        assert (result.width, result.height) == (60, 30)
        assert [p.name for p in (tmp_path / "processed").iterdir()] == ["p.jpg"]


class TestRemoveProcessed:
    def test_removes_the_variant(self, tmp_path):
        src = make_image(tmp_path / "gone.jpg")
        ingest.process_photo(src, tmp_path)
        ingest.remove_processed("gone.jpg", tmp_path)
        assert not (tmp_path / "processed" / "gone.jpg").exists()

    def test_missing_variant_is_fine(self, tmp_path):
        ingest.remove_processed("never.jpg", tmp_path)
