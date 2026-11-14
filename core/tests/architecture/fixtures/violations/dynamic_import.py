"""Violation fixture: dynamic imports only in the plugin registry."""

import importlib

module = importlib.import_module("app.storage")
