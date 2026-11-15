"""Idempotency-Key replay, digests, multipart spooling and body limits."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.access.idempotency as idempotency
from tests.access.support import (
    access_env,
    assert_problem,
    assert_security_headers,
    chunked,
    install_draft_submit,
    install_reference_upload,
    multipart_body,
    multipart_content_type,
)
from tests.conftest import pair

DRAFT_PATH = "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/draft"
DRAFT_BODY = {"base_revision": 1, "message": "hello", "card_id": None}
REFERENCE_PATH = "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/references"


def _json_request(
    client: TestClient, key: str, body: bytes
):  # type: ignore[no-untyped-def]
    return client.post(
        DRAFT_PATH,
        content=body,
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
    )


def test_same_key_and_body_replays_the_stored_response(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "json-replay-key-01"

    first = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
    )
    assert first.status_code == 202, first.text
    assert_security_headers(first)

    replay = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
    )
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert replay.headers["content-type"].startswith("application/json")
    assert_security_headers(replay)
    assert len(calls) == 1


def test_json_key_order_and_whitespace_share_the_same_digest(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "json-canonical-key-01"

    first = _json_request(
        client, key, b'{"message":"hello","base_revision":1,"card_id":null}'
    )
    assert first.status_code == 202, first.text
    second = _json_request(
        client, key, b'{ "card_id": null, "base_revision": 1, "message": "hello" }'
    )
    assert second.status_code == 202, second.text
    assert second.json() == first.json()
    assert len(calls) == 1


def test_same_key_with_another_body_is_a_conflict(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "json-mismatch-key-01"

    first = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
    )
    assert first.status_code == 202
    mismatch = client.post(
        DRAFT_PATH,
        json={"base_revision": 1, "message": "different", "card_id": None},
        headers={"Idempotency-Key": key},
    )
    assert_problem(mismatch, 409, "idempotency_mismatch")
    assert len(calls) == 1


def test_same_key_across_routes_is_a_conflict(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "json-route-key-01"
    assert (
        client.post(
            DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
        ).status_code
        == 202
    )
    mismatch = client.post(
        "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/script",
        json={"base_revision": 1},
        headers={"Idempotency-Key": key},
    )
    assert_problem(mismatch, 409, "idempotency_mismatch")
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("literal", "key"),
    [
        ("1.0", "nonint-float-one"),
        ("1e0", "nonint-float-exp"),
        ("1e400", "nonint-float-inf"),
        ("NaN", "nonint-nan"),
        ("Infinity", "nonint-infinity"),
        ("-Infinity", "nonint-neg-infinity"),
    ],
)
def test_non_integer_json_numbers_are_rejected(
    client: TestClient, monkeypatch, literal: str, key: str
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    body = f'{{"base_revision":1,"message":{literal}}}'.encode()
    response = _json_request(client, key, body)
    assert_problem(response, 422, "validation_failed")
    assert calls == []


def test_float_and_string_bodies_do_not_share_a_digest(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "float-string-key-01"

    rejected = _json_request(
        client, key, b'{"base_revision":1,"message":1.0,"card_id":null}'
    )
    assert_problem(rejected, 422, "validation_failed")

    accepted = _json_request(
        client, key, b'{"base_revision":1,"message":"1.0","card_id":null}'
    )
    assert accepted.status_code == 202, accepted.text
    assert len(calls) == 1


def test_json_body_over_one_mib_is_rejected_while_streaming(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    assert idempotency.JSON_BODY_MAX_BYTES == 1 << 20
    key = "json-too-large-key-01"

    def oversized():  # type: ignore[no-untyped-def]
        yield b'{"base_revision":1,"message":"'
        yield b"x" * idempotency.JSON_BODY_MAX_BYTES
        yield b'"}'

    rejected = client.post(
        DRAFT_PATH,
        content=oversized(),
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
    )
    assert_problem(rejected, 413, "payload_too_large")
    assert calls == []

    # The refused body did not reserve the key.
    accepted = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
    )
    assert accepted.status_code == 202
    assert len(calls) == 1

    declared = client.post(
        DRAFT_PATH,
        content=b"{" + b"x" * (idempotency.JSON_BODY_MAX_BYTES + 1),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "json-too-large-key-02",
        },
    )
    assert_problem(declared, 413, "payload_too_large")
    assert len(calls) == 1


def test_multipart_digest_ignores_boundary_filename_and_field_order(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_reference_upload(monkeypatch, client.app)
    key = "multipart-replay-key-01"
    data = b"the same reference bytes"

    first_body = multipart_body(
        [("base_revision", "1"), ("note", "alpha")],
        data,
        boundary="first-boundary",
        filename="first.mp4",
    )
    first = client.post(
        REFERENCE_PATH,
        content=first_body,
        headers={
            "Content-Type": multipart_content_type("first-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert first.status_code == 202, first.text

    second_body = multipart_body(
        [("note", "alpha"), ("base_revision", "1")],
        data,
        boundary="second-boundary",
        filename="second.mp4",
    )
    second = client.post(
        REFERENCE_PATH,
        content=second_body,
        headers={
            "Content-Type": multipart_content_type("second-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert second.status_code == 202, second.text
    assert second.json() == first.json()
    assert_security_headers(second)
    assert len(calls) == 1


def test_multipart_changed_fields_are_a_conflict(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_reference_upload(monkeypatch, client.app)
    key = "multipart-mismatch-key-01"
    data = b"same bytes"

    first = client.post(
        REFERENCE_PATH,
        content=multipart_body(
            [("base_revision", "1")], data, boundary="one-boundary"
        ),
        headers={
            "Content-Type": multipart_content_type("one-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert first.status_code == 202
    changed = client.post(
        REFERENCE_PATH,
        content=multipart_body(
            [("base_revision", "2")], data, boundary="two-boundary"
        ),
        headers={
            "Content-Type": multipart_content_type("two-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert_problem(changed, 409, "idempotency_mismatch")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "malformed",
    [
        multipart_body(
            [("base_revision", "1")],
            b"file",
            boundary="truncated",
            closing=False,
        ),
        b'--broken\r\nContent-Type: video/mp4\r\n\r\nfile\r\n--broken--\r\n',
        b"not multipart at all",
    ],
)
def test_malformed_or_truncated_multipart_is_rejected(
    client: TestClient, monkeypatch, malformed: bytes
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_reference_upload(monkeypatch, client.app)
    key = "multipart-broken-key-01"
    boundary = "truncated" if b"--truncated" in malformed else "broken"

    response = client.post(
        REFERENCE_PATH,
        content=malformed,
        headers={
            "Content-Type": multipart_content_type(boundary),
            "Idempotency-Key": key,
        },
    )
    assert_problem(response, 422, "validation_failed")
    assert calls == []

    # A broken body must not reserve the key for a later good body.
    accepted = client.post(
        REFERENCE_PATH,
        content=multipart_body(
            [("base_revision", "1")], b"file", boundary="good-boundary"
        ),
        headers={
            "Content-Type": multipart_content_type("good-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert accepted.status_code == 202, accepted.text
    assert len(calls) == 1


def test_upload_limit_stops_a_streaming_multipart_body(
    app_settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    settings = app_settings.model_copy(deep=True)
    settings.app.uploads.reference_max_bytes = 1024
    with access_env(settings) as env:
        pair(env.client)
        _job, calls = install_reference_upload(monkeypatch, env.app)
        key = "multipart-limit-key-01"
        body = multipart_body(
            [("base_revision", "1")],
            b"x" * 4096,
            boundary="large-boundary",
        )
        response = env.client.post(
            REFERENCE_PATH,
            content=chunked(body, 512),
            headers={
                "Content-Type": multipart_content_type("large-boundary"),
                "Idempotency-Key": key,
            },
        )
        assert_problem(response, 413, "payload_too_large")
        assert calls == []

        accepted = env.client.post(
            REFERENCE_PATH,
            content=multipart_body(
                [("base_revision", "1")], b"ok", boundary="small-boundary"
            ),
            headers={
                "Content-Type": multipart_content_type("small-boundary"),
                "Idempotency-Key": key,
            },
        )
        assert accepted.status_code == 202, accepted.text
        assert len(calls) == 1


def test_nonmultipart_upload_is_rejected_before_the_body_is_read(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_reference_upload(monkeypatch, client.app)
    consumed: list[bool] = []

    def body():  # type: ignore[no-untyped-def]
        consumed.append(True)
        yield b'{"base_revision":1}'

    response = client.post(
        REFERENCE_PATH,
        content=body(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "multipart-wrong-type-01",
        },
    )
    assert_problem(response, 415, "unsupported_media")
    assert consumed == []
    assert calls == []


def test_duplicate_idempotency_key_header_is_rejected(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    key = "duplicate-header-key-01"

    response = client.post(
        DRAFT_PATH,
        json=DRAFT_BODY,
        headers=[
            ("Idempotency-Key", key),
            ("Idempotency-Key", key + "-again"),
        ],
    )
    assert_problem(response, 422, "validation_failed")
    assert calls == []

    accepted = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": key}
    )
    assert accepted.status_code == 202
    assert len(calls) == 1


def test_invalid_idempotency_key_is_rejected(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_draft_submit(monkeypatch, client.app)
    response = client.post(
        DRAFT_PATH, json=DRAFT_BODY, headers={"Idempotency-Key": "short"}
    )
    assert_problem(response, 422, "validation_failed")
    assert calls == []


def test_spool_rolls_over_under_the_cache_directory(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _job, calls = install_reference_upload(monkeypatch, client.app)
    real_spool = idempotency.SpooledTemporaryFile
    recorded: dict[str, list[object]] = {"dirs": [], "rolled": []}

    class RecordingSpool(real_spool):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            recorded["dirs"].append(kwargs.get("dir"))

        def rollover(self):  # type: ignore[no-untyped-def]
            super().rollover()
            recorded["rolled"].append(self._rolled)

    monkeypatch.setattr(idempotency, "SpooledTemporaryFile", RecordingSpool)
    key = "spool-rollover-key-01"
    response = client.post(
        REFERENCE_PATH,
        content=multipart_body(
            [("base_revision", "1")],
            b"r" * (idempotency.SPOOL_MEMORY_BYTES + 4096),
            boundary="spool-boundary",
        ),
        headers={
            "Content-Type": multipart_content_type("spool-boundary"),
            "Idempotency-Key": key,
        },
    )
    assert response.status_code == 202, response.text
    assert len(calls) == 1

    cache_dir = Path(client.app.state.runtime.settings.cache_dir).resolve()
    assert len(recorded["dirs"]) == 1
    assert Path(recorded["dirs"][0]).resolve() == cache_dir  # type: ignore[arg-type]
    assert recorded["rolled"] == [True]
