from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from environment_agent.agent import EnvironmentAgent
from environment_agent.diagnosis import diagnose_workspace
from environment_agent.manager_payload import build_manager_payload
from environment_agent.mock_store import MockEnvironmentStore, StoreResourceNotFound
from environment_agent.quality import build_quality_report
from environment_agent.schemas import (
    AgentStepRequest,
    AgentStepResponse,
    EventLedgerView,
    RUN_ID_PATTERN,
    SimulationRequest,
    SimulationResponse,
)
from environment_agent.validation import PlanValidationError


app = FastAPI(title="Workspace-Bench Environment Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = MockEnvironmentStore()
MAX_RUN_STORES = 32
RunId = Annotated[str, Query(min_length=1, max_length=48, pattern=RUN_ID_PATTERN)]
run_stores: OrderedDict[str, MockEnvironmentStore] = OrderedDict()
run_stores_lock = RLock()
agent = EnvironmentAgent()


@app.exception_handler(PlanValidationError)
def plan_validation_exception_handler(
    _request: Request,
    exc: PlanValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "error": "plan_validation_failed",
                "validation_report": exc.report.model_dump(),
            }
        },
    )


@app.exception_handler(StoreResourceNotFound)
def store_resource_not_found_exception_handler(
    _request: Request,
    exc: StoreResourceNotFound,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": {
                "error": "store_resource_not_found",
                "resource_type": exc.resource_type,
                "resource_id": exc.resource_id,
            }
        },
    )


def reset_mock_store_for_tests() -> None:
    global store, run_stores
    with run_stores_lock:
        store = MockEnvironmentStore()
        run_stores = OrderedDict()


def _store_for_run(run_id: str | None = None) -> MockEnvironmentStore:
    if run_id in (None, "", "default"):
        return store
    with run_stores_lock:
        if run_id in run_stores:
            run_stores.move_to_end(run_id)
            return run_stores[run_id]
        if len(run_stores) >= MAX_RUN_STORES:
            run_stores.popitem(last=False)
        run_stores[run_id] = MockEnvironmentStore()
        return run_stores[run_id]


def _persist_agent_response(
    target_store: MockEnvironmentStore,
    workspace_id: str,
    response: AgentStepResponse,
) -> None:
    if response.updated_workspace_state is None:
        return
    target_store.set_workspace_state(response.updated_workspace_state)
    target_store.append_event(workspace_id, response.external_event)
    target_store.append_generated_tasks(workspace_id, response.task_opportunities)
    target_store.append_step_response(workspace_id, response)


def _run_agent_step_from_store(target_store: MockEnvironmentStore, request: FromStoreRequest) -> AgentStepResponse:
    with target_store.locked():
        event_index = target_store.next_event_index(request.workspace_id)
        agent_request = AgentStepRequest(
            user_profile=target_store.get_user_profile(request.user_id),
            environment_profile=target_store.get_environment_profile(request.environment_id),
            workspace_state=target_store.get_workspace_state(request.workspace_id),
            historical_tasks=target_store.get_historical_tasks(request.workspace_id),
            seed=request.seed,
            event_index=event_index,
            apply_to_mock_state=request.apply_to_mock_state,
        )
        response = agent.step(agent_request)
        _persist_agent_response(target_store, request.workspace_id, response)
        return response


class FromStoreRequest(BaseModel):
    user_id: str
    environment_id: str
    workspace_id: str
    run_id: str = Field(default="default", min_length=1, max_length=48, pattern=RUN_ID_PATTERN)
    seed: int = 0
    apply_to_mock_state: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/environment-agent/backend")
def get_backend():
    return agent.planner_backend_info


@app.get("/profiles/user/{user_id}")
def get_user_profile(user_id: str, run_id: RunId = "default"):
    return _store_for_run(run_id).get_user_profile(user_id)


@app.get("/profiles/environment/{environment_id}")
def get_environment_profile(environment_id: str, run_id: RunId = "default"):
    return _store_for_run(run_id).get_environment_profile(environment_id)


@app.get("/workspace/{workspace_id}/state")
def get_workspace_state(workspace_id: str, run_id: RunId = "default"):
    return _store_for_run(run_id).get_workspace_state(workspace_id)


@app.get("/workspace/{workspace_id}/tasks/history")
def get_historical_tasks(workspace_id: str, run_id: RunId = "default"):
    return _store_for_run(run_id).get_historical_tasks(workspace_id)


@app.get("/workspace/{workspace_id}/events", response_model=EventLedgerView)
def get_events(workspace_id: str, run_id: RunId = "default") -> EventLedgerView:
    target_store = _store_for_run(run_id)
    target_store.get_workspace_state(workspace_id)
    return EventLedgerView(workspace_id=workspace_id, event_ids=target_store.list_event_ids(workspace_id))


@app.get("/workspace/{workspace_id}/inspect")
def inspect_workspace(workspace_id: str, run_id: RunId = "default"):
    target_store = _store_for_run(run_id)
    state = target_store.get_workspace_state(workspace_id)
    history = target_store.get_historical_tasks(workspace_id)
    event_ids = target_store.list_event_ids(workspace_id)
    return {
        "workspace_id": workspace_id,
        "snapshot_id": state.current_snapshot_id,
        "event_count": len(event_ids),
        "task_count": len(history.items),
        "artifact_count": len(state.artifacts),
        "dependency_edge_count": len(state.dependency_edges),
        "metrics": state.metrics,
    }


@app.post("/workspace/{workspace_id}/reset")
def reset_workspace(workspace_id: str, run_id: RunId = "default"):
    target_store = _store_for_run(run_id)
    target_store.reset_workspace(workspace_id)
    return target_store.get_workspace_state(workspace_id)


@app.get("/workspace/{workspace_id}/quality")
def get_workspace_quality(workspace_id: str, run_id: RunId = "default"):
    target_store = _store_for_run(run_id)
    state = target_store.get_workspace_state(workspace_id)
    report = build_quality_report(target_store.list_step_responses(workspace_id), state)
    history = target_store.get_historical_tasks(workspace_id)
    report["task_coverage"]["historical_task_count"] = len(history.items)
    return report


@app.post("/environment-agent/diagnose")
def diagnose(request: FromStoreRequest):
    target_store = _store_for_run(request.run_id)
    user = target_store.get_user_profile(request.user_id)
    environment = target_store.get_environment_profile(request.environment_id)
    workspace = target_store.get_workspace_state(request.workspace_id)
    history = target_store.get_historical_tasks(request.workspace_id)
    return diagnose_workspace(user, environment, workspace, history)


@app.post("/environment-agent/step", response_model=AgentStepResponse)
def step(request: AgentStepRequest) -> AgentStepResponse:
    return agent.step(request)


@app.post("/environment-agent/step/from-store", response_model=AgentStepResponse)
def step_from_store(request: FromStoreRequest) -> AgentStepResponse:
    target_store = _store_for_run(request.run_id)
    return _run_agent_step_from_store(target_store, request)


@app.post("/environment-agent/manager-payload/from-store")
def manager_payload_from_store(request: FromStoreRequest):
    target_store = _store_for_run(request.run_id)
    response = _run_agent_step_from_store(target_store, request)
    return build_manager_payload(response)


@app.post("/environment-agent/simulate", response_model=SimulationResponse)
def simulate(request: SimulationRequest) -> SimulationResponse:
    target_store = _store_for_run(request.run_id)
    with target_store.locked():
        if request.reset_before_run:
            target_store.reset_workspace(request.workspace_id)

        responses: list[AgentStepResponse] = []
        for offset in range(request.steps):
            event_index = target_store.next_event_index(request.workspace_id)
            agent_request = AgentStepRequest(
                user_profile=target_store.get_user_profile(request.user_id),
                environment_profile=target_store.get_environment_profile(request.environment_id),
                workspace_state=target_store.get_workspace_state(request.workspace_id),
                historical_tasks=target_store.get_historical_tasks(request.workspace_id),
                seed=request.seed + offset,
                event_index=event_index,
                apply_to_mock_state=True,
            )
            response = agent.step(agent_request)
            assert response.updated_workspace_state is not None
            _persist_agent_response(target_store, request.workspace_id, response)
            responses.append(response)

        return SimulationResponse(
            workspace_id=request.workspace_id,
            steps=responses,
            final_workspace_state=target_store.get_workspace_state(request.workspace_id),
            event_ids=target_store.list_event_ids(request.workspace_id),
        )
