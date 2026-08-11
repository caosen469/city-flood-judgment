# -*- coding: utf-8 -*-
"""SSE streaming tests — ``stream_pipeline`` (ADR-0005 §6).

Asserts the SSE wire format and event ordering (``thinking*`` → ``stage``×4 →
``done``), plus the ``error`` variant on a Stage-1 hard failure. Runs with the
same fake stage callables as the seam tests — no VLM / network / city data.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _knowledge_fixtures import make_context, make_grounded, make_observation
from _pipeline_fixtures import DUMMY_IMAGE_URL, build_deps

from pipeline.streaming import format_sse, stream_pipeline
from pipeline.service import AnalysisError  # noqa: F401 — asserted via events


def _parse_sse_messages(stream):
    """Split a concatenated SSE string into (event, data) pairs."""
    msgs = []
    for chunk in stream.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        event, data = None, None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        msgs.append((event, json.loads(data) if data else None))
    return msgs


class FormatSse(unittest.TestCase):
    def test_single_line_json(self):
        msg = format_sse("thinking", {"delta": "想\n中"})  # newline inside value
        self.assertTrue(msg.endswith("\n\n"))
        head, _, data_line = msg.partition("\n")
        self.assertEqual(head, "event: thinking")
        self.assertTrue(data_line.startswith("data: "))
        # The JSON payload is on one line (EventSource splits on per-line data:).
        payload = json.loads(data_line[len("data: "):])
        self.assertEqual(payload, {"delta": "想\n中"})


class StreamOrdering(unittest.TestCase):
    def test_thinking_then_stages_then_done(self):
        deps = build_deps(reasoning_deltas=["甲", "乙"])
        stream = "".join(stream_pipeline(DUMMY_IMAGE_URL, None, deps=deps, request_id="r1"))
        msgs = _parse_sse_messages(stream)
        events = [e for e, _ in msgs]

        # thinking* come first.
        self.assertEqual(events[:2], ["thinking", "thinking"])
        # then exactly four stage events in order.
        self.assertEqual(events.count("stage"), 4)
        stage_events = [m for m in msgs if m[0] == "stage"]
        self.assertEqual(
            [d["stage"] for _, d in stage_events],
            ["observation", "grounding", "context", "knowledge"],
        )
        # the last event is done with the full AnalysisResult.
        self.assertEqual(events[-1], "done")
        done_data = msgs[-1][1]
        self.assertEqual(done_data["request_id"], "r1")
        self.assertEqual(set(done_data.keys()),
                         {"request_id", "observation", "grounding", "context", "knowledge", "timings"})

    def test_stage_payloads_carry_model_and_duration(self):
        deps = build_deps()
        stream = "".join(stream_pipeline(DUMMY_IMAGE_URL, None, deps=deps, request_id="r2"))
        msgs = _parse_sse_messages(stream)
        obs_stage = next(d for e, d in msgs if e == "stage" and d["stage"] == "observation")
        self.assertIn("waterlogging", obs_stage["data"])  # Observation model dump
        self.assertGreaterEqual(obs_stage["duration_ms"], 0.0)

    def test_thinking_omitted_when_no_deltas(self):
        deps = build_deps()  # no reasoning_deltas
        stream = "".join(stream_pipeline(DUMMY_IMAGE_URL, None, deps=deps, request_id="r3"))
        events = [e for e, _ in _parse_sse_messages(stream)]
        self.assertNotIn("thinking", events)


class StreamError(unittest.TestCase):
    def test_unreadable_image_emits_error_then_closes(self):
        deps = build_deps()
        stream = "".join(stream_pipeline("/no/such/file.png", None, deps=deps, request_id="r4"))
        msgs = _parse_sse_messages(stream)
        self.assertEqual([e for e, _ in msgs], ["error"])
        self.assertEqual(msgs[0][1]["code"], "unreadable_image")
        self.assertEqual(msgs[0][1]["stage"], "observation")

    def test_vlm_failure_error_code(self):
        from observation.generate import ObservationGenerationError

        def broken(image_source, **kwargs):
            raise ObservationGenerationError("JSON 解析失败")

        deps = build_deps()
        deps.generate_observation = broken
        stream = "".join(stream_pipeline(DUMMY_IMAGE_URL, None, deps=deps, request_id="r5"))
        msgs = _parse_sse_messages(stream)
        self.assertEqual(msgs[-1][0], "error")
        self.assertEqual(msgs[-1][1]["code"], "vlm_json_invalid")


if __name__ == "__main__":
    unittest.main()
