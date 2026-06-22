import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from findingchart_guiplotter.image_fetchers import centered_tan_wcs
from findingchart_guiplotter.models import ChartSettings, ImageData, Target
from findingchart_guiplotter.catalog import CatalogSource
from findingchart_guiplotter.renderer import (
    INSET_DISPLAY_LINEAR_SCALE,
    apply_rgb_stretch,
    arcsec_label,
    background_noise_sigma,
    compass_length_arcsec,
    injected_total_flux_from_peak_snr,
    resolve_annotation_color,
    resolve_plot_colormap,
    estimate_catalog_flux_scale,
    recommended_injected_magnitude,
    injected_reference_mag,
    magnitude_flux_scale,
    catalog_source_color,
    contrast_stretch,
    field_size_scale,
    image_display_extent,
    image_fov_arcsec,
    inset_source_box_arcsec,
    inset_axes_size_percent,
    inset_crosshair_radii_pixels,
    inset_scalebar_length_arcsec,
    main_crosshair_radii_pixels,
    main_scalebar_length_for_field_arcsec,
    marker_unit_vectors,
    world_to_scalar_pixel,
)
from findingchart_guiplotter.empirical_psf import inject_psf, moffat_kernel


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
    width, height = inset_axes_size_percent(nx=600, ny=750)

    assert width == pytest.approx(100.0 * INSET_DISPLAY_LINEAR_SCALE * 100 / 600)
    assert height == pytest.approx(100.0 * INSET_DISPLAY_LINEAR_SCALE * 100 / 750)


def test_inset_axes_size_keeps_default_square_size_and_readable_minimum():
    assert inset_axes_size_percent(nx=100, ny=100) == pytest.approx((33.333333333333336, 33.333333333333336))
    assert inset_axes_size_percent(nx=10000, ny=100) == pytest.approx((5.0, 33.333333333333336))


def test_inset_zoom_changes_sampled_area_not_inset_frame_size():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((240, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=240, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    default_box = inset_source_box_arcsec(image, ChartSettings(inset_zoom_factor=6.0))
    zoomed_box = inset_source_box_arcsec(image, ChartSettings(inset_zoom_factor=12.0))

    assert zoomed_box == pytest.approx(0.5 * default_box)
    assert inset_axes_size_percent(nx=360, ny=240) == pytest.approx((22.22222222222222, 33.333333333333336))


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
    assert inset_source_box_arcsec(image) == pytest.approx(180.0 / 6.0)


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


def test_inset_source_box_respects_custom_zoom_factor():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    assert inset_source_box_arcsec(image, ChartSettings(inset_zoom_factor=9.0)) == pytest.approx(20.0)


def test_inset_scalebar_length_stays_below_third_fov_multiple_of_four():
    assert inset_scalebar_length_arcsec(scale=1.0, shape=(90, 120)) == pytest.approx(28.0)
    assert inset_scalebar_length_arcsec(scale=0.5, shape=(60, 80)) == pytest.approx(8.0)


def test_main_scalebar_length_tracks_field_size_examples():
    assert main_scalebar_length_for_field_arcsec(180.0) == pytest.approx(60.0)
    assert main_scalebar_length_for_field_arcsec(120.0) == pytest.approx(60.0)
    assert main_scalebar_length_for_field_arcsec(90.0) == pytest.approx(30.0)
    assert main_scalebar_length_for_field_arcsec(60.0) == pytest.approx(24.0)


def test_arcsec_label_formats_arcminutes():
    assert arcsec_label(60.0) == "1'"
    assert arcsec_label(120.0) == "2'"
    assert arcsec_label(30.0) == "0.5'"
    assert arcsec_label(24.0) == "0.4'"
    assert arcsec_label(28.0) == '28"'


def test_crosshair_sizes_scale_linearly_with_field_size():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image_3arcmin = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )
    image_1p5arcmin = ImageData(
        data=np.zeros((180, 180)),
        wcs=centered_tan_wcs(target, nx=180, ny=180, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    assert field_size_scale(image_3arcmin) == pytest.approx(1.0)
    assert field_size_scale(image_1p5arcmin) == pytest.approx(0.5)

    main_default = main_crosshair_radii_pixels(image_3arcmin, psf_fwhm_arcsec=1.0)
    main_small = main_crosshair_radii_pixels(image_1p5arcmin, psf_fwhm_arcsec=1.0)
    inset_default = inset_crosshair_radii_pixels(image_3arcmin, scale_arcsec_per_pix=0.5, psf_fwhm_arcsec=1.0)
    inset_small = inset_crosshair_radii_pixels(image_1p5arcmin, scale_arcsec_per_pix=0.5, psf_fwhm_arcsec=1.0)

    assert main_default[0] == pytest.approx(1.4)
    assert main_small[0] == pytest.approx(main_default[0])
    assert main_small[1] == pytest.approx(0.5 * main_default[1])
    assert inset_default[0] == pytest.approx(1.4)
    assert inset_small[0] == pytest.approx(inset_default[0])
    assert inset_small[1] == pytest.approx(0.5 * inset_default[1])


def test_inset_crosshair_scales_linearly_with_zoom_factor():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    default_radii = inset_crosshair_radii_pixels(image, scale_arcsec_per_pix=0.5, psf_fwhm_arcsec=1.0, zoom_factor=6.0)
    zoomed_radii = inset_crosshair_radii_pixels(image, scale_arcsec_per_pix=0.5, psf_fwhm_arcsec=1.0, zoom_factor=12.0)

    assert zoomed_radii[0] == pytest.approx(2.0 * default_radii[0])
    assert zoomed_radii[1] == pytest.approx(2.0 * default_radii[1])


def test_crosshair_inner_radius_tracks_injected_psf_fwhm():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    main_inner, _ = main_crosshair_radii_pixels(image, psf_fwhm_arcsec=2.0)
    inset_inner, _ = inset_crosshair_radii_pixels(image, scale_arcsec_per_pix=0.5, psf_fwhm_arcsec=2.0, zoom_factor=6.0)

    assert main_inner == pytest.approx(2.8)
    assert inset_inner == pytest.approx(2.8)


def test_crosshair_outer_radius_has_minimum_width_of_one_point_five_fwhm():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.zeros((40, 40)),
        wcs=centered_tan_wcs(target, nx=40, ny=40, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    inner, outer = main_crosshair_radii_pixels(image, psf_fwhm_arcsec=2.0)

    assert inner == pytest.approx(2.8)
    assert outer == pytest.approx(6.0)


def test_compass_length_scales_linearly_with_field_size():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image_3arcmin = ImageData(
        data=np.zeros((360, 360)),
        wcs=centered_tan_wcs(target, nx=360, ny=360, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )
    image_1p5arcmin = ImageData(
        data=np.zeros((180, 180)),
        wcs=centered_tan_wcs(target, nx=180, ny=180, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )

    assert compass_length_arcsec(image_3arcmin) == pytest.approx(21.6)
    assert compass_length_arcsec(image_1p5arcmin) == pytest.approx(10.8)


def test_contrast_stretch_defaults_to_arcsinh_and_selects_modes():
    assert contrast_stretch(ChartSettings()).__class__.__name__ == "AsinhStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="linear")).__class__.__name__ == "LinearStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="sqrt")).__class__.__name__ == "SqrtStretch"
    assert contrast_stretch(ChartSettings(contrast_stretch="log")).__class__.__name__ == "LogStretch"


def test_plot_colormap_defaults_and_supports_builtin_and_palette_maps():
    assert resolve_plot_colormap("unknown").name == "gray_r"
    assert resolve_plot_colormap("inferno").name == "inferno"
    assert resolve_plot_colormap("inferno", invert=True).name == "inferno_r"
    assert resolve_plot_colormap("icefire").name == "icefire"
    assert resolve_plot_colormap("Hiroshige").name == "Hiroshige"


def test_annotation_color_defaults_and_accepts_supported_choices():
    assert resolve_annotation_color("unknown") == "xkcd:bright red"
    assert resolve_annotation_color("xkcd:dodger blue") == "xkcd:dodger blue"
    assert resolve_annotation_color("xkcd:bright yellow") == "xkcd:bright yellow"


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


def test_chart_settings_default_to_moffat_psf():
    assert ChartSettings().psf_model == "moffat"


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


def test_catalog_source_colors_distinguish_catalogs():
    assert catalog_source_color(type("Source", (), {"catalog": "Gaia DR3"})()) == "cyan"
    assert catalog_source_color(type("Source", (), {"catalog": "Pan-STARRS DR2"})()) == "lightcoral"


def test_recommended_injected_magnitude_gets_brighter_for_higher_target_snr():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    image = ImageData(
        data=np.random.default_rng(123).normal(0.0, 0.5, size=(181, 181)),
        wcs=centered_tan_wcs(target, nx=181, ny=181, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )
    kernel = moffat_kernel(4.0, size=81)
    for x, y, flux in [
        (40.0, 42.0, 1800.0),
        (92.0, 55.0, 1600.0),
        (138.0, 68.0, 1700.0),
        (58.0, 126.0, 1500.0),
        (126.0, 134.0, 1750.0),
    ]:
        image.data = inject_psf(image.data, kernel, x=x, y=y, flux=flux)

    mag_10sigma = recommended_injected_magnitude(image, target, target_snr=10.0, fwhm_arcsec=2.0)
    mag_20sigma = recommended_injected_magnitude(image, target, target_snr=20.0, fwhm_arcsec=2.0)
    mag_40sigma = recommended_injected_magnitude(image, target, target_snr=40.0, fwhm_arcsec=2.0)

    assert 8.0 <= mag_10sigma <= 24.0
    assert mag_20sigma == pytest.approx(18.0)
    assert 8.0 <= mag_40sigma <= 24.0
    assert mag_40sigma < mag_10sigma


def test_injected_flux_tracks_peak_snr_consistently_across_fov_changes():
    target = Target(display_name="T", ra_deg=210.0, dec_deg=54.0)
    rng = np.random.default_rng(321)
    full_noise = rng.normal(0.0, 0.5, size=(181, 181))
    wide_image = ImageData(
        data=full_noise.copy(),
        wcs=centered_tan_wcs(target, nx=181, ny=181, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )
    narrow_image = ImageData(
        data=full_noise[30:151, 30:151].copy(),
        wcs=centered_tan_wcs(target, nx=121, ny=121, pixscale_arcsec=0.5),
        survey="test",
        band="r",
        mode="Single band",
    )
    kernel = moffat_kernel(4.0, size=81)
    settings = ChartSettings(psf_magnitude=18.0)

    wide_flux = injected_total_flux_from_peak_snr(wide_image.data, settings, kernel)
    narrow_flux = injected_total_flux_from_peak_snr(narrow_image.data, settings, kernel)
    kernel_peak = float(kernel.max())

    wide_peak_snr = wide_flux * kernel_peak / background_noise_sigma(wide_image.data)
    narrow_peak_snr = narrow_flux * kernel_peak / background_noise_sigma(narrow_image.data)

    assert wide_peak_snr == pytest.approx(20.0)
    assert narrow_peak_snr == pytest.approx(20.0)
