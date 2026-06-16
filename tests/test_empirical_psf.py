import numpy as np
import pytest

from findingchart_guiplotter.empirical_psf import inject_psf, radial_edge_taper, shift_psf_to_subpixel, smooth_psf_wings


def test_smooth_psf_wings_removes_edge_floor_but_keeps_core():
    psf = np.full((11, 11), 0.001)
    psf[5, 5] = 1.0

    cleaned = smooth_psf_wings(psf)

    assert np.all(cleaned[0, :] == 0.0)
    assert np.all(cleaned[:, 0] == 0.0)
    assert cleaned[5, 5] > 0.9


def test_radial_edge_taper_fades_smoothly_to_zero():
    taper = radial_edge_taper((21, 21), start_fraction=0.55)

    assert taper[10, 10] == pytest.approx(1.0)
    assert 0.0 < taper[10, 18] < 1.0
    assert taper[0, 0] == pytest.approx(0.0)


def test_subpixel_shift_keeps_edges_zero_and_normalized():
    psf = np.full((11, 11), 0.001)
    psf[5, 5] = 1.0
    psf /= psf.sum()

    shifted = shift_psf_to_subpixel(psf, dx=0.35, dy=-0.25)

    assert shifted.sum() == pytest.approx(1.0)
    assert np.max(shifted[0, :]) == 0.0
    assert np.max(shifted[:, 0]) == 0.0


def test_inject_psf_fades_stamp_edges_to_zero():
    data = np.zeros((25, 25))
    y, x = np.mgrid[:11, :11]
    psf = np.exp(-0.5 * ((x - 5) ** 2 + (y - 5) ** 2) / 2.0**2)
    psf[5, 5] = 1.0
    psf /= psf.sum()

    injected = inject_psf(data, psf, x=12.0, y=12.0, flux=100.0)
    stamp = injected[7:18, 7:18]

    assert np.max(stamp[0, :]) == 0.0
    assert np.max(stamp[-1, :]) == 0.0
    assert np.max(stamp[:, 0]) == 0.0
    assert np.max(stamp[:, -1]) == 0.0
    assert stamp[5, 9] < stamp[5, 7] < stamp[5, 5]
    assert stamp[5, 5] > 0.0
