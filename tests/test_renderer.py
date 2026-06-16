import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from findingchart_guiplotter.image_fetchers import centered_tan_wcs
from findingchart_guiplotter.models import ChartSettings, ImageData, Target
from findingchart_guiplotter.catalog import CatalogSource
from findingchart_guiplotter.renderer import (
    INSET_DISPLAY_LINEAR_SCALE,
    INSET_SOURCE_BOX_FOV_FRACTION,
    apply_rgb_stretch,
    arcsec_label,
    estimate_catalog_flux_scale,
    estimate_target_flux_by_mode,
    injected_reference_mag,
    magnitude_flux_scale,
    catalog_source_color,
    contrast_stretch,
    image_display_extent,
    image_with_injected_psf,
    image_fov_arcsec,
    inset_source_box_arcsec,
    inset_axes_size_percent,
    inset_scalebar_length_arcsec,
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


def test_inset_scalebar_length_stays_below_third_fov_multiple_of_four():
    assert inset_scalebar_length_arcsec(scale=1.0, shape=(90, 120)) == pytest.approx(28.0)
    assert inset_scalebar_length_arcsec(scale=0.5, shape=(60, 80)) == pytest.approx(8.0)


def test_arcsec_label_formats_arcminutes():
    assert arcsec_label(60.0) == "1'"
    assert arcsec_label(120.0) == "2'"
    assert arcsec_label(28.0) == '28"'


def test_contrast_stretch_defaults_to_arcsinh_and_selects_modes():
    assert contrast_stretch(ChartSettings()).__class__.__name__ == "AsinhStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="linear")).__class__.__name__ == "LinearStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="sqrt")).__class__.__name__ == "SqrtStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="log")).__class__.__name__ == "LogStretch"


def test_apply_rgb_stretch_preserves_shape_and_bounds():
    data = np.linspace(0, 1, 27).reshape((3, 3, 3))

    stretched = apply_rgb_stretch(data, ChartSettings(contrast_stretch="sqrt"))

    assert stretched.shape == data.shape
    assert np.nanmin(stretched) >= 0.0
    assert np.nanmax(stretched) <= 1.0


def test_injected_magnitude_scale_uses_catalog_style_flux_relation():
    assert injected_reference_mag(ChartSettings(psf_magnitude=18.0)) == pytest.approx(18.0)
    assert injected_reference_mag(ChartSettings(psf_magnitude=10.0)) == pytest.approx(10.0)
    assert magnitude_flux_scale(10.0, reference_mag=18.0) == pytest.approx(10 ** 3.2)
    assert magnitude_flux_scale(22.0, reference_mag=18.0) == pytest.approx(10 ** -1.6)


def test_catalog_flux_scale_uses_loaded_catalog_sources_as_zero_point():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((101, 101)),
        wcs=centered_tan_wcs(target, nx=101, ny=101, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )
    target_coord = SkyCoord(target.ra_deg * u.deg, target.dec_deg * u.deg)
    source_a_coord = target_coord.spherical_offsets_by(10.0 * u.arcsec, 0.0 * u.arcsec)
    source_b_coord = target_coord.spherical_offsets_by(-12.0 * u.arcsec, 8.0 * u.arcsec)
    source_a = CatalogSource(
        ra_deg=source_a_coord.ra.deg,
        dec_deg=source_a_coord.dec.deg,
        label="Gaia A",
        magnitude=16.0,
        magnitude_band="G",
    )
    source_b = CatalogSource(
        ra_deg=source_b_coord.ra.deg,
        dec_deg=source_b_coord.dec.deg,
        label="Gaia B",
        magnitude=17.0,
        magnitude_band="G",
    )
    zero_point = 8.0
    for source in (source_a, source_b):
        x, y = world_to_scalar_pixel(image, SkyCoord(source.ra_deg * u.deg, source.dec_deg * u.deg))
        image.data[int(round(y)), int(round(x))] = 10 ** (zero_point - 0.4 * source.magnitude)

    flux = estimate_catalog_flux_scale(
        image.data,
        image,
        target,
        ChartSettings(psf_magnitude=18.0, catalog_sources=[source_a, source_b]),
        fwhm_pix=1.5,
    )

    assert flux == pytest.approx(10 ** (zero_point - 0.4 * 18.0), rel=0.05)


def test_catalog_calibrated_mode_requires_catalog_zero_point():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((51, 51)),
        wcs=centered_tan_wcs(target, nx=51, ny=51, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )

    flux = estimate_target_flux_by_mode(
        image.data,
        image,
        target,
        ChartSettings(psf_magnitude=18.0, psf_flux_mode="catalog-calibrated"),
        fwhm_pix=1.5,
        mode="catalog-calibrated",
    )

    assert flux is None


def test_visual_fallback_mode_produces_flux_without_catalog_sources():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.arange(51 * 51, dtype=float).reshape((51, 51)),
        wcs=centered_tan_wcs(target, nx=51, ny=51, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )

    flux = estimate_target_flux_by_mode(
        image.data,
        image,
        target,
        ChartSettings(psf_magnitude=18.0, psf_flux_mode="visual fallback"),
        fwhm_pix=1.5,
        mode="visual fallback",
    )

    assert flux is not None
    assert flux > 0


def test_catalog_calibrated_mode_skips_injection_without_catalog_scale():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((51, 51)),
        wcs=centered_tan_wcs(target, nx=51, ny=51, pixscale_arcsec=1.0),
        survey="test",
        band="r",
        mode="Single band",
    )

    injected = image_with_injected_psf(
        image,
        target,
        ChartSettings(psf_magnitude=18.0, psf_flux_mode="catalog-calibrated"),
    )

    assert np.array_equal(injected, image.data)


def test_catalog_source_colors_distinguish_catalogs():
    assert catalog_source_color(type("Source", (), {"catalog": "Gaia DR3"})()) == "cyan"
    assert catalog_source_color(type("Source", (), {"catalog": "Pan-STARRS DR2"})()) == "lightcoral"
