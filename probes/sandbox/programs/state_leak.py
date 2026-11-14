"""Measure: does one Pyodide instance share state between two code units?

Two units in one instance stand in for a reused worker. The report says whether
the module table, the virtual file system, and a monkey patch survive from the
first unit to the second.
"""

import json
import os
import sys

MARKER_PATH = "probe-leak-marker.txt"


def _first_unit():
    sys.modules["probe_leak_marker"] = object()
    with open(MARKER_PATH, "w", encoding="utf-8") as handle:
        handle.write("written")
    json.dumps = lambda *args, **kwargs: "patched"


def _second_unit():
    patches = __import__("json").dumps("x") == "patched"
    return {
        "module": "probe_leak_marker" in sys.modules,
        "file": os.path.exists(MARKER_PATH),
        "patch": patches,
    }


def run():
    original = json.dumps
    _first_unit()
    try:
        return _second_unit()
    finally:
        json.dumps = original
