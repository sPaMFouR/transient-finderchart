import numpy as np
import pytest

from findingchart_guiplotter.empirical_psf import inject_psf, shift_psf_to_subpixel, suppress_psf_background


def test_suppress_psf_background_removes_low_edge_floor():
    psf = np.full((11, 11), 0.001)
    psf[5, 5] = 1.0

    cleaned = suppress_psf_background(psf, threshold_sigma=2.0)

    assert np.all(cleaned[0, :] == 0.0)
    assert np.all(cleaned[:, 0] == 0.0)
    assert cleaned[5, 5] > 0.9


def test_subpixel_shift_keeps_edges_suppressed_and_normalized():
    psf = np.full((11, 11), 0.001)
    psf[5, 5] = 1.0
    psf /= psf.sum()

    shifted = shift_psf_to_subpixel(psf, dx=0.35, dy=-0.25)

    assert shifted.sum() == pytest.approx(1.0)
    assert np.max(shifted[0, :]) == 0.0
    assert np.max(shifted[:, 0]) == 0.0


def test_inject_psf_does_not_add_rectangular_floor():
    data = np.zeros((25, 25))
    psf = np.full((11, 11), 0.001)
    psf[5, 5] = 1.0
    psf /= psf.sum()

    injected = inject_psf(data, psf, x=12.0, y=12.0, flux=100.0)
    stamp = injected[7:18, 7:18]

    assert np.max(stamp[0, :]) == 0.0
    assert np.max(stamp[-1, :]) == 0.0
    assert np.max(stamp[:, 0]) == 0.0
    assert np.max(stamp[:, -1]) == 0.0
    assert stamp[5, 5] > 0.0
