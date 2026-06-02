"""
plot_style.py
=============
Shared plotting style for the 1987A-like SN Host-Galaxy project.

Import this at the top of every plotting script:

    from plot_style import *            # brings in set_plotparams, palettes, etc.
    # or, from a subdirectory:
    import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
    from plot_style import *

Style conventions
-----------------
* plt.style.use('science')  +  text.usetex = True
* Axis labels: fontsize=22
* Legend: fontsize=18, shadow=True, fancybox=True
* set_plotparams() applied to every linear-scale axis
* Sequential/diverging palettes from pypalettes ('hiroshige')
* Discrete object colours defined below; consistent across all figures
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.ticker import MultipleLocator, LogLocator, LogFormatterSciNotation
from matplotlib.lines import Line2D

# ── Science style + LaTeX ──────────────────────────────────────────────────────
try:
    import scienceplots          # pip install SciencePlots
    plt.style.use("science")
except ImportError:
    print("WARNING: scienceplots not installed — using default style. pip install SciencePlots")

plt.rcParams.update({
    "text.usetex":       True,
    "font.family":       "serif",
    "font.size":         18,
    "axes.labelsize":    22,
    "axes.titlesize":    20,
    "legend.fontsize":   18,
    "xtick.labelsize":   18,
    "ytick.labelsize":   18,
    "figure.dpi":        150,
    "savefig.dpi":       300,
    "savefig.bbox":      "tight",
    "lines.linewidth":   2.0,
    "lines.markersize":  10,
    "errorbar.capsize":  3,
})

# ── Colour palettes ────────────────────────────────────────────────────────────
try:
    from pypalettes import load_cmap     # pip install pypalettes
    HIROSHIGE   = load_cmap("Hiroshige")        # full continuous map
    HIROSHIGE_R = load_cmap("Hiroshige", reverse=True)
    # Discrete samples for comparison populations
    _N_COMP = 6
    COMP_COLORS = [HIROSHIGE(i / (_N_COMP - 1)) for i in range(_N_COMP)]
    COL_TYPE_II   = COMP_COLORS[0]   # warm gold
    COL_TYPE_IIb  = COMP_COLORS[1]
    COL_TYPE_IIn  = COMP_COLORS[2]
    COL_TYPE_Ib   = COMP_COLORS[3]
    COL_TYPE_Ic   = COMP_COLORS[4]
    COL_TYPE_IcBL = COMP_COLORS[5]
except ImportError:
    print("WARNING: pypalettes not installed — using fallback colours. pip install pypalettes")
    HIROSHIGE     = plt.cm.viridis
    HIROSHIGE_R   = plt.cm.viridis_r
    COL_TYPE_II   = "#AAAAAA"
    COL_TYPE_IIb  = "#2CA02C"
    COL_TYPE_IIn  = "#FF7F0E"
    COL_TYPE_Ib   = "#9467BD"
    COL_TYPE_Ic   = "#8C564B"
    COL_TYPE_IcBL = "#E377C2"

# ── 1987A-like sample object colours ─────────────────────────────────────────
COL_SECURE   = "#1A5276"   # deep navy — secure 1987A-like
COL_CAND     = "#AED6F1"   # light blue — candidates
COL_MUSE     = "#C0392B"   # deep red — MUSE-observed (highlight)
COL_EXCL     = "#BDC3C7"   # grey — excluded

# Global vs local aperture
APT_COL  = {"global": "#1A5276", "local": "#C0392B"}
APT_FILL = {"global": "#AED6F1", "local": "#F1948A"}

# MUSE-target set
MUSE_SNE = frozenset({
    "2006au", "2009mw", "2012gg", "2018anu", "2018imj",
    "2021adyl", "2021wun", "2022ymc", "DES16C3cje",
    "OGLE-2003-NOOS-005", "PTF09gpn",
})

# ── Filter colours / markers for SED plots ────────────────────────────────────
FILT_GROUPS = {
    "UV":  ["GALEX_FUV", "GALEX_NUV"],
    "Opt": ["SDSS_u", "SDSS_g", "SDSS_r", "SDSS_i", "SDSS_z",
            "PanSTARRS_g", "PanSTARRS_r", "PanSTARRS_i", "PanSTARRS_z", "PanSTARRS_y",
            "DES_g", "DES_r", "DES_i", "DES_z", "DES_Y"],
    "NIR": ["2MASS_J", "2MASS_H", "2MASS_K"],
    "MIR": ["WISE_W1", "WISE_W2", "WISE_W3", "WISE_W4"],
}

try:
    _hiro = [HIROSHIGE(x) for x in np.linspace(0.05, 0.95, 4)]
except Exception:
    _hiro = ["#9b59b6", "#2ecc71", "#e67e22", "#e74c3c"]

FILT_GRP_COL = {
    "UV":  _hiro[0],
    "Opt": _hiro[1],
    "NIR": _hiro[2],
    "MIR": _hiro[3],
}


def filter_group(fname):
    for grp, filters in FILT_GROUPS.items():
        if fname in filters:
            return grp
    return "Opt"


def filter_color(fname):
    return FILT_GRP_COL.get(filter_group(fname), "#555555")


# ── Core function: set_plotparams ─────────────────────────────────────────────

def set_plotparams(ax_obj, xticks=(1, 0.5), yticks=(1, 0.5), grid=True, fs=18,
                   tick_major=(1.6, 9), tick_minor=(1.0, 5)):
    """
    Apply consistent tick and grid styling to a linear-scale matplotlib axis.

    Parameters
    ----------
    ax_obj     : matplotlib.axes.Axes
    xticks     : (major, minor) tick spacing  — MultipleLocator values
    yticks     : (major, minor) tick spacing
    grid       : bool — show major grid
    fs         : tick label font size (default 18)
    tick_major : (width, length) for major ticks (default 1.6, 9)
    tick_minor : (width, length) for minor ticks (default 1.0, 5)

    Safety
    ------
    If the requested spacing would generate > 500 ticks on either axis
    (e.g. because the axis range is unexpectedly large), the locators are
    scaled up automatically to keep the tick count sensible.  This prevents
    the matplotlib MAXTICKS warning on histogram/scatter panels where the
    data range exceeds the caller's assumption.

    Usage example
    -------------
    fig, ax = plt.subplots()
    ax.plot(...)
    set_plotparams(ax, xticks=(1, 0.5), yticks=(1, 0.5), fs=18)
    """
    MAX_TICKS = 500   # safety cap — scale spacing if axis range is too large

    def _safe_spacing(spacing, ax_lim):
        lo, hi = ax_lim
        span = abs(hi - lo)
        if span <= 0 or spacing <= 0:
            return spacing
        n_ticks = span / spacing
        if n_ticks > MAX_TICKS:
            # Round up to a "nice" multiple: 1, 2, 5, 10, 20, 50, …
            import math
            factor = math.ceil(n_ticks / MAX_TICKS)
            for nice in [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000]:
                if spacing * nice >= spacing * factor:
                    return spacing * nice
            return spacing * factor
        return spacing

    if grid:
        ax_obj.grid(True, which="major", ls="--", lw=1.0, alpha=0.2)
    ax_obj.xaxis.set_ticks_position("both")
    ax_obj.yaxis.set_ticks_position("both")

    # Apply safety-capped tick spacings
    xlim = ax_obj.get_xlim()
    ylim = ax_obj.get_ylim()
    xmaj = _safe_spacing(xticks[0], xlim)
    xmin = _safe_spacing(xticks[1], xlim)
    ymaj = _safe_spacing(yticks[0], ylim)
    ymin = _safe_spacing(yticks[1], ylim)

    ax_obj.xaxis.set_major_locator(MultipleLocator(xmaj))
    ax_obj.xaxis.set_minor_locator(MultipleLocator(xmin))
    ax_obj.yaxis.set_major_locator(MultipleLocator(ymaj))
    ax_obj.yaxis.set_minor_locator(MultipleLocator(ymin))
    ax_obj.tick_params(axis="both", which="major",
                       direction="in", width=tick_major[0], length=tick_major[1],
                       color="k", labelsize=fs)
    ax_obj.tick_params(axis="both", which="minor",
                       direction="in", width=tick_minor[0], length=tick_minor[1],
                       color="k", labelsize=fs)


def set_plotparams_log(ax_obj, axis="both", grid=True, fs=18):
    """
    Apply consistent tick styling to a LOG-SCALE axis.
    Uses LogLocator instead of MultipleLocator — call after set_xscale/set_yscale.

    Parameters
    ----------
    ax_obj : matplotlib.axes.Axes
    axis   : 'x', 'y', or 'both'
    """
    if grid:
        ax_obj.grid(True, which="major", ls="--", lw=1.0, alpha=0.2)
        ax_obj.grid(True, which="minor", ls=":", lw=0.5, alpha=0.2)
    ax_obj.xaxis.set_ticks_position("both")
    ax_obj.yaxis.set_ticks_position("both")
    if axis in ("x", "both"):
        ax_obj.xaxis.set_major_locator(LogLocator(base=10, numticks=10))
        ax_obj.xaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=50))
    if axis in ("y", "both"):
        ax_obj.yaxis.set_major_locator(LogLocator(base=10, numticks=10))
        ax_obj.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10), numticks=50))
    ax_obj.tick_params(axis="both", which="major",
                       direction="in", width=1.6, length=9,
                       color="k", labelsize=fs)
    ax_obj.tick_params(axis="both", which="minor",
                       direction="in", width=1.0, length=5,
                       color="k", labelsize=fs)


# ── Legend helper ─────────────────────────────────────────────────────────────

def styled_legend(ax, **kwargs):
    """Apply the project legend style with sensible defaults."""
    defaults = dict(
        fontsize=18, frameon=True, shadow=True,
        fancybox=True, framealpha=0.9,
        handlelength=1.8, handletextpad=0.5,
    )
    defaults.update(kwargs)
    return ax.legend(**defaults)


# ── Standard legend handles ───────────────────────────────────────────────────

def sample_legend_handles():
    """Return the standard set of Line2D legend handles for our sample classes."""
    return [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=COL_SECURE,
               markersize=12, markeredgecolor="k", markeredgewidth=0.5,
               label=r"Secure 1987A-like"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor=COL_CAND,
               markersize=10, markeredgecolor="#4C72B0", markeredgewidth=0.8,
               label=r"Candidate"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor=COL_MUSE,
               markersize=16, markeredgecolor="k", markeredgewidth=0.5,
               label=r"1987A-like (MUSE observed)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=COL_TYPE_II,
               markersize=10, alpha=0.6, label=r"Type II (comparison)"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor=COL_TYPE_IIb,
               markersize=10, alpha=0.6, label=r"Type IIb"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=COL_TYPE_Ib,
               markersize=10, alpha=0.6, label=r"Type Ib"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor=COL_TYPE_Ic,
               markersize=10, alpha=0.6, label=r"Type Ic"),
    ]


# ── Save helper ───────────────────────────────────────────────────────────────

def savefig(fig, path_no_ext):
    """
    Save a figure as both PDF (publication) and JPG (quick view).

    Parameters
    ----------
    fig         : matplotlib Figure
    path_no_ext : Path or str without extension, e.g. 'figures/blast_sfms'
    """
    from pathlib import Path
    p = Path(path_no_ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p.with_suffix(".pdf"), dpi=2000, format="pdf", bbox_inches="tight")
    fig.savefig(p.with_suffix(".jpg"), dpi=300,  format="jpg", bbox_inches="tight")
    print(f"    Saved {p.stem}.pdf / .jpg")


def savefig_light(fig, path_no_ext, dpi_pdf: int = 300, dpi_jpg: int = 300):
    """
    Memory-safe save for large multi-panel figures.
    Uses lower DPI than savefig() to avoid OOM on figures with many subplots.

    Parameters
    ----------
    fig         : matplotlib Figure
    path_no_ext : Path or str without extension
    dpi_pdf     : int  PDF resolution (default 300 — publication quality)
    dpi_jpg     : int  JPG resolution (default 150 — screen quality)
    """
    from pathlib import Path
    p = Path(path_no_ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p.with_suffix(".pdf"), dpi=dpi_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(p.with_suffix(".jpg"), dpi=dpi_jpg, format="jpg", bbox_inches="tight")
    print(f"    Saved {p.stem}.pdf / .jpg")
