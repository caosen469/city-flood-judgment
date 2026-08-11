"""Local SRTM GeoTIFF reader shared by the Elevation and Terrain providers.

A thin wrapper around a single opened rasterio dataset that:

* samples one pixel (point elevation), and
* reads a square window around the point with nodata masked (used for both the
  surrounding-stats window and the multi-scale TPI windows).

**Negative elevations are kept.** Nansha is a delta — ~49% of SRTM pixels are
below 0 m (river channels, reclaimed land below sea level) and that low-lying
signal is exactly what the Terrain provider turns into TerrainRisk. Only the
SRTM nodata sentinel (-32768) is masked. (See ticket #13 resolution note +
ticket #11 downstream note.)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.windows import Window

DEFAULT_SRTM_TIF = Path("data/urban/nansha_srtm30m.tif")

# Meters per degree approximations for converting the (degree) pixel size to a
# metric radius label. Good enough for ``SurroundingStats.radius_m`` reporting.
_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON = 111_320.0


@dataclass
class SrtmReader:
    """Open dataset handle + nodata sentinel. Construct once, share across
    providers (FastAPI lifespan)."""

    _src: rasterio.io.DatasetReader
    nodata: float

    @classmethod
    def open(cls, path: str | Path = DEFAULT_SRTM_TIF) -> "SrtmReader":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"SRTM 缓存不存在：{path}。请先运行 scripts/download_srtm.py（#11）。"
            )
        src = rasterio.open(path)
        nodata = src.nodata if src.nodata is not None else -32768.0
        return cls(_src=src, nodata=float(nodata))

    # ------------------------------------------------------------------ #
    def pixel_size_m(self, lat: float) -> float:
        """Approx metric size of one pixel at this latitude (SRTM pixels are
        nearly square in meters)."""
        xdeg, ydeg = self._src.res
        return float((xdeg * _M_PER_DEG_LON + ydeg * _M_PER_DEG_LAT) * 0.5 * np.cos(np.radians(lat)))

    def in_bounds(self, lon: float, lat: float) -> bool:
        b = self._src.bounds
        return b.left <= lon <= b.right and b.bottom <= lat <= b.top

    def sample_point(self, lon: float, lat: float) -> Optional[float]:
        """Elevation at the pixel containing (lon, lat). ``None`` if the point is
        outside the tile or lands on nodata."""
        if not self.in_bounds(lon, lat):
            return None
        row, col = self._src.index(lon, lat)
        val = float(self._src.read(1, window=Window(col, row, 1, 1))[0, 0])
        if val == self.nodata or np.isnan(val):
            return None
        return val

    def read_window(
        self, lon: float, lat: float, radius_px: int
    ) -> tuple[np.ma.MaskedArray, int, int]:
        """Read a ``(2*radius_px+1)`` square window centered on (lon, lat).

        Returns ``(masked_array, point_row, point_col)`` where the point
        coordinates are the center cell of the window. Out-of-tile cells are
        filled with nodata and then masked, so a point near the tile edge still
        yields a usable (partial) window.
        """
        row, col = self._src.index(lon, lat)
        size = int(radius_px) * 2 + 1
        win = Window(int(col) - int(radius_px), int(row) - int(radius_px), size, size)
        arr = self._src.read(1, window=win, boundless=True, fill_value=self.nodata)
        masked = np.ma.masked_equal(arr, self.nodata)
        masked = np.ma.masked_invalid(masked)
        # point sits at the center of the requested window
        return masked, int(radius_px), int(radius_px)


def disk_mean(
    arr: np.ma.MaskedArray, radius_px: int, pr: int, pc: int
) -> tuple[Optional[float], int]:
    """Mean of valid pixels within a disk of ``radius_px`` around ``(pr, pc)``.

    Returns ``(mean, valid_count)``; mean is ``None`` when no valid pixels fall
    in the disk. Used for both surrounding elevation stats and multi-scale TPI.
    """
    h, w = arr.shape
    yy, xx = np.ogrid[:h, :w]
    disk = (yy - pr) ** 2 + (xx - pc) ** 2 <= int(radius_px) ** 2
    sub = arr[disk]
    count = int(np.ma.count(sub))
    if count == 0:
        return None, 0
    return float(np.ma.mean(sub)), count
