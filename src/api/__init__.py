"""FastAPI API package for the waterlogging demo (ADR-0005 §6/§9).

Import :mod:`api.app` for the factory (:func:`api.app.create_app`) and
:mod:`api.models` for the request/response envelopes. The ``app`` factory is
*not* imported eagerly here — doing so would create an import cycle (``app``
imports ``pipeline.service``, which imports ``api.models``), so callers import
the submodule directly.
"""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):
    # Lazy: `from api import create_app` works, but does not run at package import.
    if name == "create_app":
        from .app import create_app as _create_app

        return _create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
