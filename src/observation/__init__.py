"""Stage 1 — What I See: ``image -> Observation`` (ADR-0005 §3, §5)."""

from .generate import (
    DEFAULT_MODEL,
    REPAIR_MODEL,
    GenerateResult,
    ObservationGenerationError,
    generate_observation,
    prepare_image_input,
    validate_image_url,
)
from .prompt import build_observation_prompt, observation_json_schema

__all__ = [
    "DEFAULT_MODEL",
    "REPAIR_MODEL",
    "GenerateResult",
    "ObservationGenerationError",
    "generate_observation",
    "prepare_image_input",
    "validate_image_url",
    "build_observation_prompt",
    "observation_json_schema",
]
