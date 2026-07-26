"""Scaffold-level smoke tests."""

from app.main import app


def test_application_metadata_and_health_route() -> None:
    """The backend exposes a named FastAPI app and its liveness route."""
    assert app.title == "Vachan API"
    assert any(getattr(route, "path", None) == "/healthz" for route in app.routes)
