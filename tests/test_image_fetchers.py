import numpy as np
import pytest
from PIL import Image

from findingchart_guiplotter.image_fetchers import ImageFetchError, _legacy_jpeg_array, _legacy_placeholder_tile


def test_legacy_placeholder_tile_detects_constant_rgb_frame():
    data = np.zeros((16, 16, 3), dtype=float)
    data[..., 1] = 15.0 / 255.0
    data[..., 2] = 8.0 / 255.0

    assert _legacy_placeholder_tile(data) is True


def test_legacy_placeholder_tile_accepts_real_structure():
    yy, xx = np.mgrid[:16, :16]
    data = np.zeros((16, 16, 3), dtype=float)
    data[..., 0] = xx / 15.0
    data[..., 1] = yy / 15.0
    data[..., 2] = (xx + yy) / 30.0

    assert _legacy_placeholder_tile(data) is False


def test_legacy_jpeg_array_converts_single_band_fallback_to_grayscale():
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    rgb[..., 1] = np.arange(16, dtype=np.uint8)
    image = Image.fromarray(rgb)

    data = _legacy_jpeg_array(image, "Single band")

    assert data.shape == (16, 16)
    assert np.nanmax(data) > np.nanmin(data)


def test_legacy_jpeg_array_rejects_placeholder_tile():
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    rgb[..., 0] = 24
    rgb[..., 1] = 15
    rgb[..., 2] = 32
    image = Image.fromarray(rgb)

    with pytest.raises(ImageFetchError, match="placeholder tile"):
        _legacy_jpeg_array(image, "Color composite")
