# -*- coding: utf-8 -*-
"""FastAPI route tests — ``POST /analyze`` and ``POST /analyze/stream`` (#15).

Uses Starlette's TestClient against an app built with fake ``PipelineDeps`` (no
lifespan data load, no VLM, no city data). Asserts the hard-failure HTTP codes
(422 unreadable image) and that a happy-path 200 carries the flat
``AnalysisResult``, plus the SSE stream on the streaming endpoint.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _knowledge_fixtures import make_context, make_grounded, make_observation
from _pipeline_fixtures import build_deps

from fastapi.testclient import TestClient

from api.app import create_app
from pipeline.service import AnalysisError  # noqa: F401


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
    b"\x00\x1f\x15\xc4\x89"
)


def _client():
    deps = build_deps()
    app = create_app(deps=deps)
    return TestClient(app), deps


class AnalyzeEndpoint(unittest.TestCase):
    def test_happy_path_200(self):
        client, _ = _client()
        resp = client.post(
            "/analyze",
            data={"image_url": "https://example.com/x.png", "lat": "22.7", "lon": "113.5"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(
            set(body.keys()),
            {"request_id", "observation", "grounding", "context", "knowledge", "timings"},
        )
        self.assertIn(body["grounding"]["status"], {"grounded", "ambiguous", "unresolved"})

    def test_multipart_upload_200(self):
        client, _ = _client()
        resp = client.post(
            "/analyze",
            data={"lat": "22.7", "lon": "113.5"},
            files={"image": ("shot.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["observation"]["meta"]["source_image"], "shot.png")

    def test_no_location_200_no_location(self):
        # A ground fake that maps a None location to unresolved(no_location).
        from _pipeline_fixtures import fake_ground_no_point
        from schemas.grounding import GroundingStatus, UnresolvedReason

        entity = make_grounded(
            status=GroundingStatus.UNRESOLVED,
            reason=UnresolvedReason.NO_LOCATION,
            has_point=False,
        )
        deps = build_deps(entity=entity, ground=fake_ground_no_point(entity))
        app = create_app(deps=deps)
        client = TestClient(app)
        resp = client.post("/analyze", data={"image_url": "https://example.com/x.png"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        # no_location ⇒ grounding unresolved(no_location), degenerate context.
        self.assertEqual(body["grounding"]["status"], "unresolved")
        self.assertEqual(body["grounding"]["unresolved_reason"], "no_location")
        self.assertIsNone(body["context"]["query_point"])

    def test_missing_image_source_422(self):
        client, _ = _client()
        resp = client.post("/analyze", data={"lat": "22.7", "lon": "113.5"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"]["code"], "unreadable_image")


class StreamEndpoint(unittest.TestCase):
    def test_stream_emits_done(self):
        client, _ = _client()
        with client.stream(
            "POST",
            "/analyze/stream",
            data={"image_url": "https://example.com/x.png", "lat": "22.7", "lon": "113.5"},
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/event-stream", resp.headers["content-type"])
            # iter_bytes preserves the \n\n message separators (iter_lines drops them).
            text = b"".join(resp.iter_bytes()).decode("utf-8")

        # Split into SSE messages.
        events = []
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            ev, data = None, None
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    ev = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
            events.append((ev, json.loads(data) if data else None))

        self.assertEqual(events[-1][0], "done")
        self.assertEqual([e for e, _ in events].count("stage"), 4)
        self.assertEqual(events[-1][1]["grounding"]["status"], "grounded")

    def test_stream_unreadable_image_error_event(self):
        client, _ = _client()
        # No image_url, no file → 422 before streaming starts (request validation).
        resp = client.post("/analyze/stream", data={"lat": "22.7", "lon": "113.5"})
        self.assertEqual(resp.status_code, 422)


class AppFactory(unittest.TestCase):
    def test_create_app_with_deps_skips_lifespan_load(self):
        # deps given ⇒ app.state.deps is set; lifespan won't try to load data.
        deps = build_deps()
        app = create_app(deps=deps)
        self.assertIs(app.state.deps, deps)

    def test_503_when_deps_missing(self):
        # Simulate the lifespan failing to build production deps (e.g. city data
        # not downloaded): monkeypatch the loader to return None, and the route
        # must answer 503 rather than crash.
        import api.app as appmod
        from unittest.mock import patch

        app = create_app()  # no override ⇒ lifespan will try to load
        with patch.object(appmod, "_load_production_deps", return_value=None), \
                TestClient(app) as client:
            resp = client.post("/analyze", data={"image_url": "https://example.com/x.png"})
            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json()["detail"]["code"], "internal_error")


if __name__ == "__main__":
    unittest.main()
