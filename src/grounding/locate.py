"""``locate(LocationRef) -> LocatedPoint | None`` — the Grounding front-step
(ADR-0003).

Normalization only — *no* road matching here. Two paths:

* **lat/lon present** → pass straight through (``source`` defaults to
  ``user_latlon``; the pipeline may pass ``source=exif`` when it extracted the
  coordinates from image EXIF).
* **only raw_text / road_name** → Nominatim geocode via ``osmnx.geocoder``.

Returns ``None`` when nothing usable can be produced (empty input, or a geocode
that failed). The caller (:func:`src.grounding.ground`) maps that ``None`` to
the right ``unresolved_reason`` — ``no_location`` if the input was empty,
``geocode_failed`` if text was supplied but could not resolve.

The geocoder is injected so :mod:`tests.test_grounding_locate` runs hermetically
and so a future higher-precision geocoder (returning Nominatim ``importance``)
slots in without touching call sites. The default uses osmnx's own Nominatim
client (osmnx 2.x dropped the geopy dependency), which returns only ``(lat,
lon)``; geocode confidence therefore defaults to ``medium`` — an honest
"centroid of unknown precision", deliberately not folded into match confidence
(ADR-0003: geocoding accuracy is tracked via ``source == geocoded_text``).
"""

from __future__ import annotations

from typing import Callable, Optional

from schemas.grounding import (
    Confidence,
    CRS,
    LatLon,
    LocatedPoint,
    LocationSource,
)
from schemas.observation import LocationRef

#: A geocoder maps a free-text query to ``(lat, lon, confidence)`` or ``None``.
Geocoder = Callable[[str], "tuple[float, float, Optional[Confidence]] | None"]


def osmnx_geocoder(query: str) -> "tuple[float, float, Optional[Confidence]] | None":
    """Default geocoder: osmnx's Nominatim client. ``None`` on any failure.

    osmnx 2.x implements its own Nominatim access (no geopy) and exposes only
    coordinates — no ``importance`` — so confidence is a flat ``medium``.
    """
    try:
        import osmnx as ox  # noqa: PLC0415 — optional import kept local

        lat, lon = ox.geocoder.geocode(query)
    except Exception:  # noqa: BLE001 — any failure ⇒ geocode_failed upstream
        return None
    if lat is None or lon is None:
        return None
    return float(lat), float(lon), Confidence.MEDIUM


def _has_latlon(ref: LocationRef) -> bool:
    return ref.lat is not None and ref.lon is not None


def _has_text(ref: LocationRef) -> bool:
    return bool((ref.raw_text or "").strip() or (ref.road_name or "").strip())


def locate(
    ref: LocationRef,
    *,
    source: Optional[LocationSource] = None,
    geocoder: Optional[Geocoder] = None,
) -> Optional[LocatedPoint]:
    """Normalize a :class:`LocationRef` to a :class:`LocatedPoint` or ``None``.

    Parameters
    ----------
    ref : LocationRef
        Passthrough location from Observation meta / demo input.
    source : LocationSource, optional
        Provenance hint for the lat/lon path (``exif`` / ``user_latlon``).
        Inferred as ``user_latlon`` when omitted. Ignored on the geocode path
        (always ``geocoded_text``).
    geocoder : callable, optional
        Injected geocoder for the text path (tests). Defaults to
        :func:`osmnx_geocoder`.

    Returns
    -------
    LocatedPoint or None
        ``None`` when the input carries nothing usable, or text was supplied but
        could not be geocoded.
    """
    if ref is None:
        return None

    # Path 1 — coordinates already present (EXIF or manual entry).
    if _has_latlon(ref):
        return LocatedPoint(
            point=LatLon(lat=float(ref.lat), lon=float(ref.lon)),  # type: ignore[arg-type]
            crs=CRS.WGS84,
            source=source or LocationSource.USER_LATLON,
            geocode_confidence=None,
        )

    # Path 2 — free text / road name → geocode.
    if _has_text(ref):
        text = (ref.raw_text or ref.road_name or "").strip()
        resolve = geocoder or osmnx_geocoder
        result = resolve(text)
        if result is None:
            return None
        lat, lon, confidence = result
        return LocatedPoint(
            point=LatLon(lat=lat, lon=lon),
            crs=CRS.WGS84,
            source=LocationSource.GEOCODED_TEXT,
            geocode_confidence=confidence,
        )

    # Nothing usable.
    return None
