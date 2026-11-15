"""The instance lock outlives the workers and the state database."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

import app.main as main
from app.access.instance import acquire_instance_lock
from app.bootstrap import build_runtime
from app.storage.paths import Layout


def test_second_server_cannot_lock_while_workers_stop(app_settings) -> None:  # type: ignore[no-untyped-def]
    runtime = build_runtime(app_settings)
    state_db = Layout.from_settings(app_settings).state_db
    seen: dict[str, bool] = {}

    def watch(name: str, original: Callable[..., None]) -> Callable[..., None]:
        def wrapped(**kwargs: float | None) -> None:
            try:
                acquire_instance_lock(state_db).close()
            except RuntimeError:
                seen[name] = True
            else:
                seen[name] = False
            original(**kwargs)

        return wrapped

    runtime.runner.stop = watch("workers", runtime.runner.stop)  # type: ignore[method-assign]
    runtime.state_db.close = watch("database", runtime.state_db.close)  # type: ignore[method-assign]

    with TestClient(main.create_app(runtime, pairing_display=lambda url: None)):
        pass

    assert seen == {"workers": True, "database": True}
    acquire_instance_lock(state_db).close()
