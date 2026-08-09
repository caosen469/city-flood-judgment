# -*- coding: utf-8 -*-

"""Stage 1 generator (``src/observation/generate.py``) unit tests.

Covers JSON extraction, Pydantic validation, and the two-step repair routing —
all without touching the network, by injecting a stub OpenAI client that emits
canned stream chunks.

Run: ``python -m unittest tests.test_observation_generate -v``
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from observation.generate import (  # noqa: E402
    GenerateResult,
    ObservationGenerationError,
    _extract_json_text,
    _parse_and_validate,
    generate_observation,
)
from schemas.observation import Observation  # noqa: E402


def _delta(*, content: str | None = None, reasoning: str | None = None) -> SimpleNamespace:
    extra = {"reasoning_content": reasoning} if reasoning is not None else None
    return SimpleNamespace(content=content, model_extra=extra)


def _chunk(content: str | None = None, reasoning: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=_delta(content=content, reasoning=reasoning))])


class _FakeCompletions:
    """Streams a programmed list of chunks per call; the second call is repair."""

    def __init__(self, call_chunks: list[list[SimpleNamespace]]):
        # A queue of chunk-lists, one per create() call.
        self._calls = list(call_chunks)

    def create(self, **_kwargs):  # noqa: D401 - mirrors openai signature loosely
        if not self._calls:
            raise AssertionError("stub client was called more times than programmed")
        return list(self._calls.pop(0))


class _FakeClient:
    def __init__(self, call_chunks):
        self.chat = SimpleNamespace(completions=_FakeCompletions(call_chunks))


def _valid_observation_json() -> str:
    """A minimal, valid Observation payload (status absent → level must be L0)."""
    import json

    return json.dumps(
        {
            "phenomenon_type": "road_waterlogging",
            "overall_confidence": "high",
            "presence_probability": 0.1,
            "visible_location_text": None,
            "observed_summary": "路面干燥，无积水迹象。",
            "waterlogging": {
                "status": "absent",
                "waterlogging_level": "L0",
                "surface_condition": "dry",
            },
        },
        ensure_ascii=False,
    )


# --------------------------------------------------------------------------- #
# JSON extraction / parsing.                                                  #
# --------------------------------------------------------------------------- #


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(_extract_json_text('{"a": 1}'), '{"a": 1}')

    def test_fenced_json(self) -> None:
        self.assertEqual(_extract_json_text('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_surrounded_by_prose(self) -> None:
        self.assertEqual(_extract_json_text('here is the result {"a": 1} done'), '{"a": 1}')


class ParseAndValidateTests(unittest.TestCase):
    def test_valid_payload(self) -> None:
        obs = _parse_and_validate(_valid_observation_json())
        self.assertIsInstance(obs, Observation)
        self.assertEqual(obs.waterlogging.waterlogging_level.value, "L0")

    def test_absent_must_be_l0(self) -> None:
        import json

        payload = json.loads(_valid_observation_json())
        payload["waterlogging"]["status"] = "absent"
        payload["waterlogging"]["waterlogging_level"] = "L3"  # violates the validator
        with self.assertRaises(Exception):
            _parse_and_validate(json.dumps(payload))


# --------------------------------------------------------------------------- #
# generate_observation end-to-end with a stub client.                         #
# --------------------------------------------------------------------------- #


class GenerateObservationTests(unittest.TestCase):
    def test_success_first_pass(self) -> None:
        valid = _valid_observation_json()
        # One streamed call: a reasoning chunk then the content in two slices.
        half = len(valid) // 2
        chunks = [
            [
                _chunk(reasoning="思考中..."),
                _chunk(content=valid[:half]),
                _chunk(content=valid[half:]),
            ]
        ]
        client = _FakeClient(chunks)

        reasoning_seen: list[str] = []
        content_seen: list[str] = []
        result = generate_observation(
            "data:image/jpeg;base64,AAAA",
            client=client,
            on_reasoning=reasoning_seen.append,
            on_content=content_seen.append,
        )
        self.assertIsInstance(result, GenerateResult)
        self.assertFalse(result.repaired)
        self.assertEqual(result.observation.waterlogging.status.value, "absent")
        self.assertEqual(reasoning_seen, ["思考中..."])
        self.assertEqual("".join(content_seen), valid)

    def test_repair_path(self) -> None:
        valid = _valid_observation_json()
        # First call emits broken JSON (trailing garbage); repair call emits valid.
        broken = valid[:-1] + ",,,"
        client = _FakeClient(
            [
                [_chunk(content=broken)],
                [_chunk(content=valid)],
            ]
        )
        result = generate_observation(
            "data:image/jpeg;base64,AAAA",
            client=client,
        )
        self.assertTrue(result.repaired)
        self.assertEqual(result.observation.waterlogging.status.value, "absent")

    def test_hard_fail_when_repair_still_invalid(self) -> None:
        # Both passes emit unparseable text.
        client = _FakeClient(
            [
                [_chunk(content="not json at all")],
                [_chunk(content="still not json")],
            ]
        )
        with self.assertRaises(ObservationGenerationError):
            generate_observation("data:image/jpeg;base64,AAAA", client=client)

    def test_empty_content_hard_fails(self) -> None:
        client = _FakeClient([[_chunk(content=None)]])
        with self.assertRaises(ObservationGenerationError):
            generate_observation("data:image/jpeg;base64,AAAA", client=client)


if __name__ == "__main__":
    unittest.main()
