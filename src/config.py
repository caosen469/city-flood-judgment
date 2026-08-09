"""Pipeline + API configuration (pydantic-settings).

A single :class:`Settings` reads runtime knobs from the environment (and an
optional ``.env``), so the FastAPI lifespan and the pipeline construction root
have one place to get: the DashScope key, the default Stage-1 / Stage-3 model
ids + thinking policy, the on-disk city-data paths, and the CORS origins the
Vue dev server may call from.

The DashScope key is also read directly by :mod:`src.vlm.client` (module-level
``os.environ.get``); it is mirrored here only so the lifespan can surface a
clear startup warning and so ``KnowledgeEngine`` auto-wiring sees it through the
same channel. Nothing in this module performs network I/O.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the waterlogging demo API.

    Field names map 1:1 to upper-cased env vars (``DASHSCOPE_API_KEY``,
    ``OBSERVATION_MODEL``, …). An optional ``.env`` is loaded for local dev.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM credentials / models ---------------------------------------- #
    dashscope_api_key: str = ""

    # Stage 1 (image → Observation): hybrid-thinking VL model; thinking on by
    # default (richer reasoning), the two-step repair absorbs non-standard JSON.
    observation_model: str = "qwen3-vl-plus"
    observation_thinking: str = "auto"

    # Stage 3 (Knowledge Engine): a stable non-thinking text model so json_object
    # emits clean JSON. The engine degrades to deterministic rules without a key.
    knowledge_model: str = "qwen-plus"
    knowledge_thinking: str = "off"

    # --- On-disk city data (#11) ----------------------------------------- #
    roads_gpkg: Path = Path("data/urban/nansha_roads.gpkg")
    srtm_tif: Path = Path("data/urban/nansha_srtm30m.tif")

    # --- API -------------------------------------------------------------- #
    # Vue dev server origins permitted by CORS (Vite defaults: 5173/5174).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]


settings = Settings()
