from fastapi.testclient import TestClient
import pytest
from concurrent.futures import ThreadPoolExecutor

from api.index import app
from environment_agent.api import _store_for_run, reset_mock_store_for_tests


@pytest.fixture(autouse=True)
def fresh_mock_store():
    reset_mock_store_for_tests()


@pytest.mark.parametrize(
    ("override", "resource_type", "resource_id"),
    [
        ({"user_id": "missing_user"}, "user", "missing_user"),
        ({"environment_id": "missing_environment"}, "environment", "missing_environment"),
        ({"workspace_id": "missing_workspace"}, "workspace", "missing_workspace"),
    ],
)
def test_from_store_endpoint_returns_404_for_unknown_store_resource(
    override,
    resource_type,
    resource_id,
):
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
    }
    payload.update(override)

    response = client.post("/api/environment-agent/manager-payload/from-store", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "error": "store_resource_not_found",
        "resource_type": resource_type,
        "resource_id": resource_id,
    }


def test_simulate_endpoint_returns_404_for_unknown_workspace():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/environment-agent/simulate",
        json={
            "user_id": "user_logistics_001",
            "environment_id": "env_peak_logistics",
            "workspace_id": "missing_workspace",
            "steps": 1,
            "reset_before_run": True,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "error": "store_resource_not_found",
        "resource_type": "workspace",
        "resource_id": "missing_workspace",
    }


def test_event_ledger_endpoint_returns_404_for_unknown_workspace():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/workspace/missing_workspace/events")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "error": "store_resource_not_found",
        "resource_type": "workspace",
        "resource_id": "missing_workspace",
    }


def test_simulate_endpoint_is_scoped_by_run_id():
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
        "seed": 7,
        "steps": 1,
        "reset_before_run": True,
    }

    first_response = client.post(
        "/api/environment-agent/simulate",
        json={**payload, "run_id": "run_a"},
    )
    run_a_state = client.get("/api/workspace/workspace_logistics_demo/inspect?run_id=run_a")
    run_b_state = client.get("/api/workspace/workspace_logistics_demo/inspect?run_id=run_b")

    assert first_response.status_code == 200
    assert run_a_state.json()["event_count"] == 1
    assert run_b_state.json()["event_count"] == 0


def test_run_id_rejects_unbounded_or_unsafe_values():
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
        "run_id": "bad run id " + ("x" * 80),
        "steps": 1,
    }

    body_response = client.post("/api/environment-agent/simulate", json=payload)
    query_response = client.get(
        "/api/workspace/workspace_logistics_demo/inspect",
        params={"run_id": payload["run_id"]},
    )

    assert body_response.status_code == 422
    assert query_response.status_code == 422


def test_run_scoped_mock_stores_evict_oldest_run_after_limit():
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
        "seed": 7,
        "steps": 1,
        "reset_before_run": True,
    }

    for index in range(33):
        response = client.post(
            "/api/environment-agent/simulate",
            json={**payload, "run_id": f"run_{index:02d}"},
        )
        assert response.status_code == 200

    first_run_state = client.get(
        "/api/workspace/workspace_logistics_demo/inspect",
        params={"run_id": "run_00"},
    )
    latest_run_state = client.get(
        "/api/workspace/workspace_logistics_demo/inspect",
        params={"run_id": "run_32"},
    )

    assert first_run_state.status_code == 200
    assert first_run_state.json()["event_count"] == 0
    assert latest_run_state.json()["event_count"] == 1


def test_manager_payload_apply_to_mock_state_persists_requested_evolution():
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
        "seed": 7,
        "apply_to_mock_state": True,
    }

    before = client.get("/api/workspace/workspace_logistics_demo/inspect").json()
    response = client.post("/api/environment-agent/manager-payload/from-store", json=payload)
    after = client.get("/api/workspace/workspace_logistics_demo/inspect").json()

    assert response.status_code == 200
    assert response.json()["validation_report"]["status"] == "passed"
    assert after["event_count"] == before["event_count"] + 1
    assert after["snapshot_id"] == "snap_0002"


def test_direct_step_handles_unstructured_snapshot_id_when_applying_state():
    client = TestClient(app, raise_server_exceptions=False)
    base_store = _store_for_run("default")
    workspace = base_store.get_workspace_state("workspace_logistics_demo")
    workspace.current_snapshot_id = "snapshot-alpha"
    payload = {
        "user_profile": base_store.get_user_profile("user_logistics_001").model_dump(),
        "environment_profile": base_store.get_environment_profile("env_peak_logistics").model_dump(),
        "workspace_state": workspace.model_dump(),
        "historical_tasks": base_store.get_historical_tasks("workspace_logistics_demo").model_dump(),
        "seed": 7,
        "apply_to_mock_state": True,
    }

    response = client.post("/api/environment-agent/step", json=payload)

    assert response.status_code == 200
    assert response.json()["updated_workspace_state"]["current_snapshot_id"] == "snapshot-alpha_0001"


def test_concurrent_store_backed_steps_reserve_unique_event_indices(monkeypatch):
    original_next_event_index = _store_for_run("default").next_event_index

    def slow_next_event_index(workspace_id: str) -> int:
        import time

        time.sleep(0.02)
        return original_next_event_index(workspace_id)

    monkeypatch.setattr(_store_for_run("default"), "next_event_index", slow_next_event_index)
    payload = {
        "user_id": "user_logistics_001",
        "environment_id": "env_peak_logistics",
        "workspace_id": "workspace_logistics_demo",
        "seed": 7,
        "apply_to_mock_state": True,
    }

    def post_step(_index: int):
        client = TestClient(app, raise_server_exceptions=False)
        return client.post("/api/environment-agent/step/from-store", json=payload)

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(post_step, range(8)))

    assert [response.status_code for response in responses] == [200] * 8
    event_ids = [response.json()["external_event"]["event_id"] for response in responses]
    assert len(event_ids) == len(set(event_ids))

    ledger_response = TestClient(app).get("/api/workspace/workspace_logistics_demo/events")
    ledger_event_ids = ledger_response.json()["event_ids"]
    assert len(ledger_event_ids) == 8
    assert set(ledger_event_ids) == set(event_ids)
