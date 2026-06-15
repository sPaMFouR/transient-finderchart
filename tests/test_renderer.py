import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from finding_chart_plotter.image_fetchers import centered_tan_wcs
from finding_chart_plotter.models import ImageData, Target
from finding_chart_plotter.renderer import (
    INSET_DISPLAY_LINEAR_SCALE,
    INSET_SOURCE_BOX_FOV_FRACTION,
    catalog_source_color,
    image_display_extent,
    image_fov_arcsec,
    inset_source_box_arcsec,
    inset_axes_size_percent,
    marker_unit_vectors,
    world_to_scalar_pixel,
)


def test_centered_wcs_maps_target_to_displayed_pixel_center():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((81, 101)),
        wcs=centered_tan_wcs(target, nx=101, ny=81, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    x, y = world_to_scalar_pixel(image, SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg))

    assert x == pytest.approx(50.0)
    assert y == pytest.approx(40.0)
    assert image_display_extent(101, 81) == pytest.approx((-0.5, 100.5, -0.5, 80.5))


def test_marker_vectors_follow_east_left_north_up_wcs_orientation():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=0.0)
    image = ImageData(
        data=np.zeros((101, 101)),
        wcs=centered_tan_wcs(target, nx=101, ny=101, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )

    north, east = marker_unit_vectors(image, target)

    assert north[1] > 0.99
    assert abs(north[0]) < 0.01
    assert east[0] < -0.99
    assert abs(east[1]) < 0.01


def test_inset_axes_size_is_three_times_source_box_until_clamped():
    width, height = inset_axes_size_percent(nx=600, ny=750, box_width=100, box_height=100)

    assert width == pytest.approx(100.0 * INSET_DISPLAY_LINEAR_SCALE * 100 / 600)
    assert height == pytest.approx(100.0 * INSET_DISPLAY_LINEAR_SCALE * 100 / 750)


def test_inset_axes_size_has_readable_minimum_and_maximum():
    assert inset_axes_size_percent(nx=10000, ny=10000, box_width=10, box_height=10) == pytest.approx((5.0, 5.0))
    assert inset_axes_size_percent(nx=100, ny=100, box_width=100, box_height=100) == pytest.approx((55.0, 55.0))


def test_inset_source_box_scales_with_image_fov():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    assert image_fov_arcsec(image) == pytest.approx(180.0)
    assert inset_source_box_arcsec(image) == pytest.approx(180.0 * INSET_SOURCE_BOX_FOV_FRACTION)


def test_inset_source_box_uses_smaller_dimension_for_rectangular_images():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((240, 480)),
        wcs=centered_tan_wcs(target, nx=480, ny=240, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )

    assert image_fov_arcsec(image) == pytest.approx(240.0)
    assert inset_source_box_arcsec(image) == pytest.approx(40.0)


def test_catalog_source_colors_distinguish_catalogs():
    assert catalog_source_color(type("Source", (), {"catalog": "Gaia DR3"})()) == "orange"
    assert catalog_source_color(type("Source", (), {"catalog": "Pan-STARRS DR2"})()) == "lightgreen"
