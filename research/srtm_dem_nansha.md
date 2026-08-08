# SRTM 30m DEM Elevation Data for 广州市南沙区 (Guangzhou Nansha District)

## Overview

This document investigates how to acquire, process, and query SRTM 30m resolution DEM data covering Nansha District, Guangzhou (approximately **22.5--23.0 N, 113.3--113.7 E**), along with algorithms for identifying relative low-lying terrain to support waterlogging (积水) risk assessment.

---

## 1. Accessible Sources for SRTM 30m Data

### Comparison Matrix

| Source | Auth Required | Download Format | Coverage | Ease of Use | Best For |
|---|---|---|---|---|---|
| **bopen/elevation (CLI + Python)** | None | GeoTIFF (auto-clipped) | Global (NASA SRTMGL1 v003) | Highest | Programmatic download, quick prototyping |
| **OpenTopography API** | Free API key | GeoTIFF | Global | High | On-demand clipping via API |
| **USGS EarthExplorer** | Free account | .hgt or GeoTIFF | Global | Medium | GUI-based, bulk tile download |
| **NASA Earthdata (LP DAAC)** | Free account | .hgt | Global | Medium | Direct NASA source, programmatic access via earthaccess library |
| **srtm.py / python-srtm** | None | auto-downloads .hgt | Global | High (but low-res only) | Quick single-point lookups |

### Recommended: `bopen/elevation` -- Python package

The **elevation** package (Apache 2.0 licensed) is the most convenient option. It auto-manages tile download, caching, and clipping from NASA SRTMGL1 v003 servers.

```bash
# Requires: make, curl, unzip, gunzip, gdal
pip install elevation

# Verify installation
eio selfcheck
```

#### Download CLI for Nansha

The CLI takes bounds in WGS84 order: `left bottom right top` (lon_min, lat_min, lon_max, lat_max).

```bash
# Download SRTM 30m covering Nansha (~22.5-23.0N, 113.3-113.7E)
eio clip -o nansha_srtm30m.tif --bounds 113.3 22.5 113.7 23.0

# Add 0.02 degree margin for edge cases
eio clip -o nansha_srtm30m.tif --bounds 113.28 22.48 113.72 23.02
```

#### Python API

```python
import elevation

# Same operation from Python code
elevation.clip(
    bounds=(113.3, 22.5, 113.7, 23.0),
    output='nansha_srtm30m.tif'
)

# Cache management
elevation.seed(bounds=(113.3, 22.5, 113.7, 23.0))  # pre-download only
elevation.clean()   # fix cache after errors
```

The first download is slow (fetches tiles from USGS servers). Subsequent accesses are instant due to local caching.

### OpenTopography API

Free for non-commercial use. Requires an API key from [opentopography.org/developers](https://opentopography.org/developers).

```python
import requests

API_KEY = "your-opentopography-api-key"
url = "https://portal.opentopography.org/API/globaldem"

params = {
    "demtype": "SRTMGL1",          # SRTM 30m
    "south": 22.5,
    "north": 23.0,
    "west": 113.3,
    "east": 113.7,
    "outputFormat": "GTiff",
    "API_Key": API_KEY,
}

response = requests.get(url, params=params, stream=True)
with open("nansha_srtm_opentopo.tif", "wb") as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)
```

**Limitation**: The API clips to requested bounds server-side -- good for small regions, but may time out or limit large requests.

### USGS EarthExplorer

1. Register at [earthexplorer.usgs.gov](https://earthexplorer.usgs.gov/)
2. Search for "SRTM 1 Arc-Second Global" dataset
3. Draw bounding box or enter coordinates
4. Download `.hgt` tiles individually

**Pros**: No size restrictions, bulk download support. **Cons**: Requires manual GUI workflow; less suitable for automation.

### NASA Earthdata (LP DAAC)

1. Register at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/)
2. Use `earthaccess` Python library for authenticated programmatic access:

```bash
pip install earthaccess
```

```python
import earthaccess

earthaccess.login()

# Search for SRTMGL1 granules over Nansha
results = earthaccess.search_data(
    short_name="SRTMGL1_N",
    bounding_box=(113.3, 22.5, 113.7, 23.0),
)
earthaccess.download(results, "./nansha_srtm/")
```

---

## 2. SRTM Tile(s) Covering Nansha

SRTMGL1 tiles are named by their **southwest corner** integer latitude/longitude: `N{lat}E{lon}.hgt`.

For Nansha (22.5--23.0 N, 113.3--113.7 E), the bounding integer corners are:

- Latitude range: 22 to 23 N
- Longitude range: 113 to 114 E (for the eastern half) and 113 only (Nansha does not cross 114)

**Primary covering tile**: **`N22E113.hgt`**

This single tile spans 22--23 N, 113--114 E and fully covers Nansha District.

Verify:
```
Latitude min=22.5, max=23.0   -> within [22, 23]  YES
Longitude min=113.3, max=113.7 -> within [113, 114] YES
```

Edge cases: if your study area extends south to 22.0 or east past 114.0, you may also need:
- `N22E114.hgt` (if extending east of 114 E)
- `N21E113.hgt` (if extending south of 22 N)

### Tile file structure

Each `.hgt` file is **3601 x 3601** 16-bit signed integers (big-endian), covering a 1 x 1 tile:
- 1201 rows of latitude (22 N at row 0, 23 N at row 3600)
- 1201 columns of longitude (113 E at col 0, 114 E at col 3600)
- Pixel resolution: ~30m (1 arc-second)
- No-data value: -32768 (void areas over ocean)

---

## 3. Python Libraries: Comparison

| Library | Strengths | Weaknesses | Best For |
|---|---|---|---|
| **rasterio** | Full-featured GDAL wrapper, windowed reads, reprojection, vector/raster ops | Heavy dependency (GDAL); ~100MB install | Production pipeline, complex geospatial ops |
| **elevation** (bopen) | One-command tile download + clipping, cache management | Requires GDAL; not a data-query library itself | Data acquisition |
| **srtm.py** (tkrajina) | Ultra-lightweight (~50KB), auto-downloads `.hgt`, simple `get_elevation(lat, lon)` | Only handles `.hgt` raw format; single-point lookup only; no terrain statistics | Quick elevation lookups in constrained environments |
| **xarray + rioxarray** | Labeled multi-dimensional arrays, dask integration, scientific computing | Overhead for simple DEM use cases | Multi-file analysis, time-series DEM |
| **richdem** | Native C++ depression filling, TPI, slope, flow accumulation -- very fast | Only accepts numpy arrays (no direct GeoTIFF I/O) | Hydrological terrain analysis |
| **pyflwdir** | Flow direction, catchment delineation, depression filling | Requires setup; fewer users | Full watershed hydrology |

### Recommendation

Use **rasterio** for I/O + basic queries, and **richdem** or **pyflwdir** for terrain analysis (depression detection). Avoid `srtm.py` for this project -- it does single-point lookups without surrounding terrain statistics.

### Library versions & dependencies

```bash
pip install rasterio         # GDAL wrapper for reading/writing
pip install richdem           # high-performance terrain analysis (C++)
pip install pyflwdir          # flow direction + hydrology tools
pip install xarray rioxarray  # optional: labeled multi-dim arrays
pip install elevation         # data acquisition
pip install earthaccess       # NASA Earthdata authenticated access
```

---

## 4. Efficient Elevation Query: Lat/Lon + Surrounding Statistics

### Core logic

Given a (lat, lon) point, we need:
1. Single elevation value at that point
2. min / max / mean / std within a configurable radius (e.g., 500m, 1km, 2km)

For SRTM 30m data: 1 arc-second ~ 30m at the equator. At Nansha latitude (~22.8 N), cos(22.8 deg) = 0.922, so 1 arc-second in longitude is ~28m. Use the approximation: 1 pixel = 1 arc-second = 30m for simplicity.

Radius-to-pixel conversion:
```
radius_pixels = radius_meters / 30.0
```

### Implementation with rasterio

```python
import numpy as np
import rasterio
from rasterio.windows import Window

def point_elevation_and_stats(
    tif_path: str,
    lat: float,
    lon: float,
    radius_m: float = 500.0,
) -> dict:
    """
    Query elevation at a lat/lon point and compute terrain statistics
    within a configurable radius.
    
    Args:
        tif_path: Path to GeoTIFF DEM file (already clipped to study area).
        lat: Latitude in WGS84 decimal degrees.
        lon: Longitude in WGS84 decimal degrees.
        radius_m: Analysis radius in meters.
    
    Returns:
        dict with keys: elevation_pt, min, max, mean, std, radius_m, valid_pixels
    """
    pixel_size_m = 30.0               # SRTM 1 arc-second ~30m
    radius_px = int(radius_m / pixel_size_m)
    
    with rasterio.open(tif_path) as src:
        # Convert lat/lon to row/col (0-based pixel coordinates)
        row, col = src.index(lon, lat)
        
        # --- 1. Single point elevation ---
        pt_window = Window(col, row, 1, 1)
        pt_data = src.read(1, window=pt_window, masked=True)
        elevation_pt = float(pt_data[0, 0]) if not pt_data.mask[0, 0] else None
        
        # --- 2. Surrounding window ---
        row_start = max(0, row - radius_px)
        row_end   = min(src.height, row + radius_px + 1)
        col_start = max(0, col - radius_px)
        col_end   = min(src.width, col + radius_px + 1)
        
        window = Window(col_start, row_start,
                        col_end - col_start, row_end - row_start)
        data = src.read(1, window=window, masked=True)
        
        # Filter out no-data values
        valid = data[~data.mask].data.astype(np.float64)
    
    if len(valid) == 0:
        return {
            "elevation_pt": elevation_pt,
            "min": None, "max": None, "mean": None, "std": None,
            "radius_m": radius_m,
            "valid_pixels": 0,
        }
    
    return {
        "elevation_pt": elevation_pt,
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "radius_m": radius_m,
        "valid_pixels": len(valid),
    }
```

### Performance considerations

- **Pre-clip the DEM** to the study area (Nansha bbox) using `elevation.clip()`. Working with a ~50MB GeoTIFF is far faster than querying individual `.hgt` tiles every time.
- **Cache the open dataset handle** if doing many point queries in succession (use a class wrapping `rasterio.open`).
- For **batch queries** (e.g., 100+ points), load the entire clipped DEM into memory as a numpy array once, then use array indexing for all points:

```python
class CachedDEM:
    def __init__(self, tif_path: str):
        with rasterio.open(tif_path) as src:
            self.data = src.read(1, masked=True)
            self.transform = src.transform
            self.crs = src.crs
            self.height = src.height
            self.width = src.width
    
    def query(self, lat: float, lon: float, radius_m: float = 500.0):
        col, row = ~self.transform * (lon, lat)  # inverse transform
        row, col = int(row), int(col)
        # ... windowed stats as above using self.data[row, col]
```

---

## 5. Relative Low-Lying Detection Algorithm

### The challenge in Nansha

Nansha is predominantly **0--10m elevation** (Pearl River Delta alluvial plain). Global thresholds like "elevation < 5m" are meaningless because the entire district qualifies. The task is to find **localized depressions** -- places that are notably lower than their immediate surroundings, making them prone to water accumulation.

### Recommended approach: Multi-scale Topographic Position Index (TPI) + Depression Depth

#### Method 1: Local elevation anomaly (simplest, effective for flat terrain)

For each query point, compute how much lower it is relative to its local neighborhood:

```python
def relative_lowness(data: np.ndarray, row: int, col: int,
                     window_size_px: int, min_valid: int = 9) -> float | None:
    """
    Relative lowness = local_mean - point_elevation.
    Positive value means the point is lower than its surroundings.
    
    Args:
        data: 2D masked array of elevations.
        row, col: center pixel coordinates.
        window_size_px: half-size of analysis window.
        min_valid: minimum valid pixels required.
    
    Returns:
        Relative lowness in meters, or None if insufficient data.
    """
    r0, r1 = max(0, row - window_size_px), min(data.shape[0], row + window_size_px + 1)
    c0, c1 = max(0, col - window_size_px), min(data.shape[1], col + window_size_px + 1)

    sub = data[r0:r1, c0:c1]
    valid = sub[~sub.mask].data.astype(np.float64)

    if len(valid) < min_valid:
        return None

    center_val = float(data[row, col])
    local_mean = float(np.mean(valid))
    return local_mean - center_val
```

### Recommended window sizes for Nansha

For SRTM 30m, these pixel radii correspond to:
| Window | Pixels (radius) | Area covered | Rationale |
|---|---|---|---|
| **Micro-depression** | 10 px (~300m) | ~600m diameter | Catch local ponding, road crown dips, small drainage features |
| **Mesoscale** | 33 px (~1km) | ~2km diameter | Identify neighborhood-scale low areas; filter out micro-variation noise |
| **Macro-scale** | 66 px (~2km) | ~4km diameter | Identify broad topographic lows in the delta landscape |

### Threshold recommendations

Based on Pearl River Delta terrain characteristics:

```python
# Multi-scale weighting
def compute_lowness_score(data, row, col):
    """
    Composite lowness score from three spatial scales.
    Returns a dict suitable for classification.
    """
    scores = {}
    scales = {
        "micro":  10,   # ~300m
        "meso":   33,   # ~1km
        "macro":  66,   # ~2km
    }
    
    for name, radius in scales.items():
        lowness = relative_lowness(data, row, col, radius)
        scores[name] = lowness
    
    # Weighted composite: meso-scale is the primary signal,
    # micro confirms local character, macro provides context
    if scores["meso"] is not None:
        composite = scores["meso"]
        if scores["micro"] is not None:
            composite += 0.3 * scores["micro"]
        if scores["macro"] is not None:
            composite += 0.2 * scores["macro"]
        scores["composite"] = composite
    
    return scores

def classify_lowness(scores: dict) -> str:
    """Classify relative lowness into risk tiers."""
    c = scores.get("composite")
    if c is None:
        return "insufficient_data"
    
    if c < 0.3:
        return "level_or_higher"
    elif c < 1.0:
        return "slightly_low"
    elif c < 2.0:
        return "moderately_low"
    else:
        return "significantly_low"
```

#### Why these thresholds?

In the 0--10m delta plain:
- A lowness of **0.3--1.0m** relative to the 1km neighborhood is notable (the area is slightly lower than average).
- A lowness of **1.0--2.0m** warrants attention (e.g., a road depression, riverbank low point).
- A lowness of **>2.0m** is strongly indicative of a local depression that will accumulate water.

#### Method 2: Depression depth via pit-filling (RichDEM)

For a more rigorous hydrogeomorphic approach, use RichDEM's fill-and-differencing method:

```python
import richdem as rd
import rasterio
import numpy as np

def compute_depression_depth(tif_path: str) -> np.ndarray:
    """
    Compute depression depth by pit-filling the DEM and
    taking the difference between filled and original surface.
    """
    # Load DEM into numpy array
    with rasterio.open(tif_path) as src:
        dem = src.read(1).astype(np.float32)
        dem[dem <= -32768] = np.nan  # mask no-data
        profile = src.profile

    # Fill no-data with a high sentinel before RichDEM (it needs a clean array)
    dem_filled_nan = np.nan_to_num(dem, nan=9999.0)

    # Convert to RichDEM array
    rdem = rd.rdarray(dem_filled_nan, no_data=9999.0)

    # Pit-fill (complete fill -- replaces depressions with flat surfaces)
    rdem_filled = rd.FillDepressions(rdem, epsilon=False, in_place=False)

    # Depression depth = filled - original
    depth = rdem_filled - rdem

    # Mask areas where depth is negligible (< 0.1m)
    depression_map = np.where(depth > 0.1, depth, 0.0)

    return depression_map
```

This method is **complementary** to the relative-lowness approach:
- **TPI/lowness** identifies topographic position relative to surroundings (continuous signal).
- **Depression depth** identifies hydrologically closed basins (binary-like signal -- either a pit or not).

### Recommended final algorithm

1. **Preprocess**: Clip SRTM 30m to Nansha bbox; save as single GeoTIFF.
2. **Compute depression depth map** using RichDEM pit-filling (once, offline).
3. **For each query point** (e.g., surveillance camera location):
   - Query SRTM elevation at the point.
   - Compute multi-scale TPI scores (micro/meso/macro).
   - Check depression depth at the point from the precomputed map.
   - Combine into a risk signal:
     ```python
     risk = (
         0.4 * normalize(tpi_composite) +
         0.3 * normalize(depression_depth) +
         0.3 * normalize(1.0 / slope)  # if slope is available
     )
     ```

---

## 6. Free Online Elevation APIs (Fallback)

### Open-Elevation (self-hosted)

- **URL**: `https://api.open-elevation.com/api/v1/lookup`
- **Status**: Public instance often unreliable/overloaded.
- **Commercial use**: Free.
- **Rate limit**: Unknown; no SLA.

```python
import requests

def open_elevation_lookup(lat: float, lon: float) -> float | None:
    url = "https://api.open-elevation.com/api/v1/lookup"
    resp = requests.get(url, params={"locations": f"{lat},{lon}"})
    if resp.status_code == 200:
        data = resp.json()
        return data["results"][0]["elevation"]
    return None
```

**Recommendation**: Do NOT rely on the public instance for production. It is a fallback only.

### OpenTopography API

Covered above in Section 1. Reliable, but requires registration + API key. Provides both tile download AND point-based queries.

### Open-Meteo Elevation API

- **URL**: `https://api.open-meteo.com/v1/elevation`
- **No API key required**
- **Rate limit**: 10,000 calls/day (free tier)
- **Resolution**: 90m (SRTM3/CGIAR)

```python
import requests

def open_meteo_elevation(lat: float, lon: float) -> float | None:
    url = "https://api.open-meteo.com/v1/elevation"
    params = {"latitude": lat, "longitude": lon}
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        return resp.json()["elevation"][0]
    return None
```

### Recommended fallback strategy

1. **Primary**: Local SRTM 30m GeoTIFF (offline, fast, full-resolution).
2. **Fallback 1**: OpenTopography API (requires API key, 30m resolution, fair rate limits).
3. **Fallback 2**: Open-Meteo (no key, 90m resolution, 10k/day limit).
4. **Fallback 3**: Open-Elevation public instance (no key, unreliable, last resort).

---

## Summary: Recommended Implementation Path

1. **Acquire data**: Use `elevation.clip(bounds=(113.3, 22.5, 113.7, 23.0), output='nansha_srtm30m.tif')` to get a single GeoTIFF covering all of Nansha.
2. **Store the file**: `nansha_srtm30m.tif` (~50MB) in the `data/` directory of this project.
3. **Build a query module** `src/dem.py` with `rasterio`:
   - `DemQuery(tif_path)` class that opens the DEM and provides `query(lat, lon, radius_m)` returning elevation + stats.
   - `CachedDemQuery(tif_path)` variant that pre-loads the array for batch performance.
4. **Build a terrain analysis module** `src/terrain.py` with `richdem`:
   - `compute_depression_depth(tif_path)` generating a precomputed depression map.
   - `relative_lowness(data, row, col, window_size)` for TPI-style scoring.
5. **API fallback**: `src/elevation_fallback.py` wrapping Open-Meteo and OpenTopography.

---

## References

- NASA SRTMGL1 v003 dataset: https://lpdaac.usgs.gov/products/srtmgl1v003/
- bopen/elevation: https://github.com/bopen/elevation
- rasterio: https://rasterio.readthedocs.io/
- RichDEM: https://richdem.readthedocs.io/
- pyflwdir: https://deltares.github.io/pyflwdir/
- OpenTopography: https://opentopography.org/developers
- Open-Elevation: https://github.com/Jorl17/open-elevation
- Open-Meteo Elevation: https://open-meteo.com/en/docs/elevation-api
- Weiss, A.D. (2001). Topographic Position and Landforms Analysis. *ESRI User Conference*.
