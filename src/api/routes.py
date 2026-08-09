"""FastAPI routes — thin wrappers over the :func:`pipeline.analyze` seam.

Both endpoints share the same multipart/form-data request shape (ADR-0005 §6):
an image source (``image_url`` *or* ``image`` file upload) plus an optional
``location`` (``lat`` / ``lon`` / ``road_name`` / ``raw_text``). Hard-failure
mapping (ADR-0005 §4): unreadable image → 422, VLM upstream / JSON-repair
failure → 502; everything else is graceful degradation inside the 200
``AnalysisResult``.
"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from observation.generate import ObservationGenerationError
from pipeline.service import (
    ObservationImageError,
    PipelineDeps,
    analyze,
    resolve_image_source,
)
from pipeline.streaming import stream_pipeline

from .models import ErrorCode, LocationRefInput

router = APIRouter()


# --------------------------------------------------------------------------- #
# Request parsing helpers.                                                    #
# --------------------------------------------------------------------------- #


def _build_location(
    lat: Optional[float],
    lon: Optional[float],
    road_name: Optional[str],
    raw_text: Optional[str],
) -> Optional[LocationRefInput]:
    """Assemble a LocationRefInput, or None when nothing usable was supplied."""
    loc = LocationRefInput(lat=lat, lon=lon, road_name=road_name, raw_text=raw_text)
    return None if loc.is_empty() else loc


async def _resolve_upload_or_url(
    image_url: Optional[str], image: Optional[UploadFile]
) -> tuple[object, str]:
    """Return ``(image_for_seam, source_image_label)``.

    The seam accepts a URL string, a path, or raw bytes. A multipart upload
    becomes bytes (label = original filename); a URL stays a string. Raises
    ``HTTPException(422)`` for a bad URL / non-image upload / both-or-neither.
    """
    if image is not None and image.filename:
        data = await image.read()
        if not data:
            raise HTTPException(
                status_code=422,
                detail={"code": ErrorCode.UNREADABLE_IMAGE.value, "message": "上传的图片为空。"},
            )
        return data, image.filename

    if image_url:
        try:
            # Validate + keep as a string; resolve_image_source re-validates.
            return image_url, image_url
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": ErrorCode.UNREADABLE_IMAGE.value, "message": str(exc)},
            ) from exc

    raise HTTPException(
        status_code=422,
        detail={
            "code": ErrorCode.UNREADABLE_IMAGE.value,
            "message": "必须提供 image_url 或 image 其一。",
        },
    )


def _get_deps(request: Request) -> PipelineDeps:
    deps: Optional[PipelineDeps] = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(
            status_code=503,
            detail={"code": ErrorCode.INTERNAL_ERROR.value, "message": "服务未就绪：pipeline 依赖未装配。"},
        )
    return deps


def _to_seam_location(loc: Optional[LocationRefInput]):
    """The seam takes a schemas.observation.LocationRef (or None)."""
    if loc is None:
        return None
    from schemas.observation import LocationRef

    return LocationRef(lat=loc.lat, lon=loc.lon, road_name=loc.road_name, raw_text=loc.raw_text)


# --------------------------------------------------------------------------- #
# Endpoints.                                                                  #
# --------------------------------------------------------------------------- #


@router.post("/analyze")
async def analyze_endpoint(
    request: Request,
    image_url: Optional[str] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
    lat: Optional[float] = Form(default=None),
    lon: Optional[float] = Form(default=None),
    road_name: Optional[str] = Form(default=None),
    raw_text: Optional[str] = Form(default=None),
):
    """Non-streaming analysis → full ``AnalysisResult``."""
    deps = _get_deps(request)
    image_for_seam, source_image = await _resolve_upload_or_url(image_url, image)
    location = _build_location(lat, lon, road_name, raw_text)
    request_id = uuid4().hex

    try:
        return analyze(
            image_for_seam,
            _to_seam_location(location),
            deps=deps,
            request_id=request_id,
            source_image=source_image,
        )
    except ObservationImageError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": ErrorCode.UNREADABLE_IMAGE.value, "message": str(exc)},
        ) from exc
    except ObservationGenerationError as exc:
        msg = str(exc)
        json_invalid = any(
            kw in msg for kw in ("JSON", "解析", "校验", "修复", "parse", "validate")
        )
        code = ErrorCode.VLM_JSON_INVALID if json_invalid else ErrorCode.VLM_PROVIDER_ERROR
        raise HTTPException(
            status_code=502,
            detail={"code": code.value, "message": msg, "stage": "observation"},
        ) from exc


@router.post("/analyze/stream")
async def analyze_stream_endpoint(
    request: Request,
    image_url: Optional[str] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
    lat: Optional[float] = Form(default=None),
    lon: Optional[float] = Form(default=None),
    road_name: Optional[str] = Form(default=None),
    raw_text: Optional[str] = Form(default=None),
):
    """Streaming analysis → SSE (thinking* → stage×4 → done | error)."""
    deps = _get_deps(request)
    image_for_seam, source_image = await _resolve_upload_or_url(image_url, image)
    location = _build_location(lat, lon, road_name, raw_text)
    request_id = uuid4().hex

    # The seam needs a validated image source. For a multipart upload we already
    # have bytes; resolve_image_source inside stream_pipeline handles both. For a
    # URL it validates. An unreadable image yields an SSE ``error`` event rather
    # than an HTTP 422 (the stream has already started).
    return StreamingResponse(
        stream_pipeline(
            image_for_seam,
            _to_seam_location(location),
            deps=deps,
            request_id=request_id,
            source_image=source_image,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
