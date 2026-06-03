from __future__ import annotations


def ensure_astropy_wcsaxes_compat() -> None:
    """Patch small Matplotlib/Astropy compatibility gaps at runtime.

    Some Astropy versions import ``AnchoredEllipse`` from
    ``mpl_toolkits.axes_grid1.anchored_artists``. Newer Matplotlib builds may no
    longer expose that symbol, which prevents WCSAxes from importing at all.
    """
    import mpl_toolkits.axes_grid1.anchored_artists as anchored_artists

    if hasattr(anchored_artists, "AnchoredEllipse"):
        return

    from matplotlib.offsetbox import AnchoredOffsetbox, AuxTransformBox
    from matplotlib.patches import Ellipse

    class AnchoredEllipse(AnchoredOffsetbox):
        def __init__(
            self,
            transform,
            width,
            height,
            angle,
            loc,
            pad=0.1,
            borderpad=0.1,
            prop=None,
            frameon=True,
            **kwargs,
        ):
            self._box = AuxTransformBox(transform)
            self.ellipse = Ellipse((0, 0), width, height, angle=angle, **kwargs)
            self._box.add_artist(self.ellipse)
            super().__init__(
                loc,
                pad=pad,
                borderpad=borderpad,
                child=self._box,
                prop=prop,
                frameon=frameon,
            )

    anchored_artists.AnchoredEllipse = AnchoredEllipse
