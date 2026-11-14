"""Violation fixture: only bootstrap may import app.settings."""

from app.settings import Settings  # noqa: F401
