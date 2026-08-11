"""FastAPI application factory + lifespan (ADR-0005 §9).

:func:`create_app` wires the production :class:`PipelineDeps` in the lifespan —
loading the OSM road network and SRTM tiff once (shared across requests),
building the default :class:`ContextAssembler` around one
:class:`SrtmReader`, and a :class:`KnowledgeEngine` (which auto-wires a DashScope
client only when ``DASHSCOPE_API_KEY`` is set, else degrades to deterministic
rules). Route tests pass ``deps=`` to skip the lifespan load and run with fakes.

Run locally::

    uvicorn api.app:app --reload      # from the repo root, with src on PYTHONPATH
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from pipeline.service import PipelineDeps, make_grounder

from .routes import router

log = logging.getLogger(__name__)


def _load_production_deps() -> Optional[PipelineDeps]:
    """Build the real PipelineDeps from on-disk city data, or None on failure.

    A missing GeoPackage / SRTM tif is logged but does not crash the app — the
    routes return 503 until the data is present. Run
    ``scripts/download_osm_roads.py`` + ``scripts/download_srtm.py`` (#11) first.
    """
    try:
        from grounding.graph import RoadNetwork

        network = RoadNetwork.from_gpkg(settings.roads_gpkg)
    except FileNotFoundError as exc:
        log.error("路网数据未就绪，pipeline 未装配：%s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — surface any loader failure at startup
        log.exception("路网加载失败：%s", exc)
        return None

    try:
        from context import make_default_assembler

        assembler = make_default_assembler(srtm_path=settings.srtm_tif)
    except FileNotFoundError as exc:
        log.error("SRTM DEM 未就绪，pipeline 未装配：%s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("Context assembler 构造失败：%s", exc)
        return None

    from knowledge import KnowledgeEngine
    from observation.generate import generate_observation

    engine = KnowledgeEngine(model=settings.knowledge_model, thinking=settings.knowledge_thinking)

    return PipelineDeps(
        generate_observation=generate_observation,
        ground=make_grounder(network),
        context_assembler=assembler,
        knowledge_engine=engine,
        observation_model=settings.observation_model,
        observation_thinking=settings.observation_thinking,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load city data + build deps once at startup (unless pre-overridden)."""
    if app.state.deps is None:
        app.state.deps = _load_production_deps()
    yield


def create_app(*, deps: Optional[PipelineDeps] = None) -> FastAPI:
    """Build the FastAPI app.

    Parameters
    ----------
    deps : PipelineDeps, optional
        Pre-built pipeline dependencies (route tests). When given, the lifespan
        skips loading city data and uses these directly.
    """
    app = FastAPI(
        title="城市积水知识理解 Demo API",
        version="0.1.0",
        description=(
            "图像 → 积水事件知识 的分析接缝（PRD §5.2 / ADR-0005）。"
            " POST /analyze 非流式；POST /analyze/stream SSE 逐阶段。"
        ),
        lifespan=lifespan,
    )

    app.state.deps = deps  # None ⇒ lifespan loads production deps
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


# A module-level app for `uvicorn api.app:app`.
app = create_app()
