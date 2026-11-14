"""The OpenAPI document and the API fixtures must match CONTRACTS section 4."""

from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import load_json

API = Path(__file__).resolve().parents[3] / "fixtures" / "api"

OPERATIONS = {
    "getHealth",
    "postSessionPair",
    "getSessionCsrf",
    "getRuntime",
    "postRuntimePrepare",
    "putCredentialsLlm",
    "getCredentialsLlm",
    "deleteCredentialsLlm",
    "listCatalog",
    "getCatalogItem",
    "getCatalogMedia",
    "createProject",
    "listProjects",
    "getProject",
    "deleteProject",
    "createVideo",
    "getVideo",
    "listVideoRevisions",
    "getVideoRevision",
    "createDraft",
    "runScript",
    "confirmScript",
    "confirmConcept",
    "createPreviews",
    "confirmScenes",
    "createChange",
    "sendMessage",
    "getChange",
    "previewChange",
    "applyChange",
    "rejectChange",
    "undoVideo",
    "runPrecheck",
    "generateVideo",
    "uploadReference",
    "linkReference",
    "createStyle",
    "createTemplate",
    "createBgmCode",
    "uploadBgm",
    "getBgmAudio",
    "createPreset",
    "listPresets",
    "listJobs",
    "getJob",
    "cancelJob",
    "retryJob",
    "getArtifact",
    "downloadVideo",
    "recordActivity",
    "getMetrics",
}


def _operations(document: dict) -> dict[str, tuple[str, str, dict]]:
    found = {}
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                found[operation_id] = (method, path, operation)
    return found


def test_openapi_has_every_contract_operation(client) -> None:  # type: ignore[no-untyped-def]
    # The client fixture builds the app with isolated directories.
    assert client.app is not None
    document = client.app.openapi()  # type: ignore[attr-defined]
    assert set(_operations(document)) == OPERATIONS


def test_every_operation_has_a_fixture() -> None:
    fixtures = {path.stem for path in API.glob("*.json")}
    assert fixtures == OPERATIONS


def test_problem_responses_are_documented(client) -> None:  # type: ignore[no-untyped-def]
    document = client.app.openapi()  # type: ignore[attr-defined]
    operation = _operations(document)["createProject"][2]
    for code in ("422", "500", "501"):
        content = operation["responses"][code]["content"]["application/problem+json"]
        assert content["schema"]["$ref"].endswith("/Problem"), code


def test_required_idempotency_headers_are_declared(client) -> None:  # type: ignore[no-untyped-def]
    document = client.app.openapi()  # type: ignore[attr-defined]
    for operation_id in ("confirmScript", "confirmScenes", "undoVideo"):
        parameters = _operations(document)[operation_id][2]["parameters"]
        assert any(
            parameter["name"] == "Idempotency-Key" and parameter["in"] == "header"
            for parameter in parameters
        ), operation_id


def _validator(document: dict, schema: dict) -> Draft202012Validator:
    return Draft202012Validator({"components": document["components"], **schema})


@pytest.mark.parametrize("operation_id", sorted(OPERATIONS))
def test_api_fixture_matches_openapi(operation_id: str, client) -> None:  # type: ignore[no-untyped-def]
    document = client.app.openapi()  # type: ignore[attr-defined]
    method, template, operation = _operations(document)[operation_id]
    fixture = load_json(f"api/{operation_id}.json")

    assert fixture["operationId"] == operation_id
    assert fixture["method"].lower() == method.lower()
    assert fixture["path_template"] == template
    concrete = template
    for name in fixture["request"]["path"]:
        assert f"{{{name}}}" in template, f"{name} is not a path parameter of {template}"
        concrete = concrete.replace(f"{{{name}}}", str(fixture["request"]["path"][name]))
    assert fixture["path"] == concrete

    body = fixture["request"]["body"]
    if body is not None:
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        _validator(document, request_schema).validate(body)

    response = fixture["response"]
    response_spec = operation["responses"][str(response["status"])]
    if response["media_type"] is not None:
        assert response_spec["description"]
        if response["body"] is not None:
            media = response_spec.get("content", {}).get(response["media_type"])
            assert media is not None, f"{response['media_type']} is not documented"
            assert "schema" in media, f"{response['media_type']} has no schema"
            _validator(document, media["schema"]).validate(response["body"])
    elif response["body"] is not None:
        response_schema = response_spec["content"]["application/json"]["schema"]
        _validator(document, response_schema).validate(response["body"])
