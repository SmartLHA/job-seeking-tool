"""Job source registry.

Each job source (Reed, Adzuna, LinkedIn, …) registers a :class:`JobSource`
adapter here at import time.  The UI layer discovers sources through this
registry and never needs to import source-specific modules directly.

Adding a new source
-------------------
1. Create ``src/job_sources/<name>_source.py``.
2. Implement the five callables described on :class:`JobSource`.
3. Call :func:`register` at module level so the registration happens on import.
4. Import the new module in ``src/job_hunt_ui.py`` alongside the existing
   ``from src.job_sources import reed_source as _rs; _ = _rs`` line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class JobSource:
    """Adapter that connects a job board to the generic UI layer.

    Attributes
    ----------
    source_id:
        Short identifier used in routes (``/search/{source_id}``,
        ``/select/{source_id}``) and stored in job records as ``source_type``.
        Must be lowercase alphanumeric, e.g. ``"reed"``, ``"adzuna"``.
    display_name:
        Human-readable label shown in the UI, e.g. ``"Reed"``.
    is_available:
        Callable that returns ``True`` when the source is properly configured
        (e.g. API key present in environment).  Called at render time.
    search_handler:
        ``(search_params: dict[str, str]) -> list[dict[str, Any]]``
        Accepts normalised search params and returns a list of UI result dicts
        (the format consumed by ``render_results``).
    select_handler:
        ``(form: dict[str, str], config: UIServerConfig | None) -> dict[str, str]``
        Converts the hidden-field POST form submitted when a user clicks
        "Review this job" into the ``evaluate`` form values dict. ``config`` is
        passed so sources that need server state (paths, model label) can use it.
        Should raise ``ValueError`` on invalid / tampered input.
    render_search_form:
        ``(values: dict[str, str], enabled: bool) -> str``
        Returns the HTML ``<form>`` block for this source's search UI.
    render_results:
        ``(results, error, nonce, more_url=None) -> str``
        Returns HTML for the search-results section (may be empty string when
        ``results`` is ``None``). ``more_url`` drives the "More jobs" pagination
        link and defaults to ``None``.
    """

    source_id: str
    display_name: str
    is_available: Callable[[], bool]
    normalize_search_params: Callable[[dict[str, str]], dict[str, str]]
    """Map raw GET query params to cleaned/defaulted search-form values.
    Calling with ``{}`` returns the default (empty) search form state."""
    search_handler: Callable[[dict[str, str]], list[dict[str, Any]]]
    """Accept the cleaned search-form values and return a list of UI result dicts."""
    select_handler: Callable[[dict[str, str], Any], dict[str, str]]
    """Convert the hidden-field POST form into ``evaluate`` form values.
    Receives ``(form, config)``. Should raise ``ValueError`` on invalid input."""
    render_search_form: Callable[[dict[str, str], bool], str]
    render_results: Callable[[list[dict[str, Any]] | None, str | None, str | None, str | None], str]
    render_cards_fragment: Callable[..., str] | None = None
    """Render just the result *cards* (no surrounding chrome) for an AJAX "More
    jobs" page. Signature ``(results, *, skip: int, nonce: str | None) -> str``.
    ``None`` means the source does not support pagination."""


_REGISTRY: dict[str, JobSource] = {}


def register(source: JobSource) -> None:
    """Register a job source.  Later calls with the same ``source_id`` replace
    the earlier registration (useful in tests)."""
    _REGISTRY[source.source_id] = source


def get_source(source_id: str) -> JobSource | None:
    """Return the registered adapter for *source_id*, or ``None``."""
    return _REGISTRY.get(source_id)


def all_sources() -> list[JobSource]:
    """Return all registered sources in registration order."""
    return list(_REGISTRY.values())
