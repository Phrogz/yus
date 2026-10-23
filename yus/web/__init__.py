"""Web front ends for a game session.

    from yus.web.dashboard import create_dashboard, run_dashboard
    app = create_dashboard(session.snapshot, session.describe)   # a Dash app; app.server is its Flask (WSGI) app
    run_dashboard(session)                                       # or view it locally at http://127.0.0.1:8050/dashboard/

See docs/dashboard.md.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_dashboard", "run_dashboard"]


def __getattr__(name: str) -> Any:  # import Dash only when the dashboard is used
    if name in __all__:
        from yus.web import dashboard

        return getattr(dashboard, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
