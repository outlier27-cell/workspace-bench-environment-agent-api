from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from typing import TypeVar

from environment_agent.schemas import (
    AgentStepResponse,
    ArtifactState,
    DependencyEdge,
    EnvironmentProfile,
    ExternalEvent,
    HistoricalTasks,
    TaskHistoryItem,
    TaskOpportunity,
    UserProfile,
    WorkspaceState,
    WorkUnitState,
)


T = TypeVar("T")


class StoreResourceNotFound(KeyError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} '{resource_id}' not found")


def _lookup(mapping: dict[str, T], resource_type: str, resource_id: str) -> T:
    try:
        return mapping[resource_id]
    except KeyError as exc:
        raise StoreResourceNotFound(resource_type, resource_id) from exc


class MockEnvironmentStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._users = {
            "user_logistics_001": UserProfile(
                user_id="user_logistics_001",
                primary_role="logistics manager",
                primary_domain="cross-border ecommerce logistics",
                core_work_activities=[
                    "monitor delayed shipments",
                    "coordinate with carriers",
                    "write weekly operations reports",
                ],
                recurring_deliverables=[
                    "weekly operations report",
                    "customer response drafts",
                    "carrier performance review",
                ],
                deadline_behavior={"deadline_sensitivity": "high", "burst_before_deadline": True},
                workspace_behavior_patterns=[
                    "keeps stale policy PDFs",
                    "reuses previous weekly report drafts",
                    "mixes carrier scorecards with order exception sheets",
                ],
                short_term_goals=["resolve delayed shipment complaints before end of day"],
            )
        }
        self._environments = {
            "env_peak_logistics": EnvironmentProfile(
                environment_id="env_peak_logistics",
                organization_type="cross-border logistics company",
                industry_domain="e-commerce logistics",
                collaboration_topology="manager + vendors + customer support + finance",
                external_event_frequency="frequent",
                deadline_intensity="high",
                incident_rate="high",
                policy_volatility="medium",
                resource_constraint_level="medium",
                seasonality="Q4 peak season",
                multi_tenant_pressure="medium",
            )
        }
        self._states = {
            "workspace_logistics_demo": WorkspaceState(
                workspace_id="workspace_logistics_demo",
                current_snapshot_id="snap_0001",
                active_work_units=[
                    WorkUnitState(
                        workunit_id="wu_weekly_ops",
                        title="Weekly logistics operations report",
                        status="active",
                        priority="medium",
                        related_entities=["carrier_A", "customer_X"],
                    )
                ],
                artifacts=[
                    ArtifactState(
                        artifact_id="art_march_shipments",
                        path="/orders/march_shipments.xlsx",
                        artifact_type="xlsx",
                        role="shipment_table",
                        workunit_id="wu_weekly_ops",
                    ),
                    ArtifactState(
                        artifact_id="art_carrier_scorecard_q1",
                        path="/vendors/carrier_scorecard_q1.xlsx",
                        artifact_type="xlsx",
                        role="carrier_scorecard",
                        workunit_id="wu_weekly_ops",
                    ),
                    ArtifactState(
                        artifact_id="art_sla_policy_q1",
                        path="/policies/sla_policy_q1.pdf",
                        artifact_type="pdf",
                        role="stale_policy_candidate",
                        workunit_id="wu_weekly_ops",
                    ),
                    ArtifactState(
                        artifact_id="art_weekly_report_draft",
                        path="/reports/weekly_ops_report_draft.docx",
                        artifact_type="docx",
                        role="weekly_report_draft",
                        workunit_id="wu_weekly_ops",
                    ),
                ],
                dependency_edges=[
                    DependencyEdge(
                        source_artifact_id="art_march_shipments",
                        target_artifact_id="art_weekly_report_draft",
                        relation="summarized_by",
                        reason="March shipment table is referenced by the weekly report draft.",
                    )
                ],
                event_log=[],
                metrics={
                    "active_work_units": 1,
                    "stale_work_units": 0,
                    "artifact_family_count": 4,
                    "cross_workunit_edges": 0,
                    "stale_file_ratio": 0.0,
                    "file_type_entropy": 0.8,
                },
            )
        }
        self._histories = {
            "workspace_logistics_demo": HistoricalTasks(
                workspace_id="workspace_logistics_demo",
                items=[
                    TaskHistoryItem(
                        task_id="task_prev_summary",
                        task_type="cross_file_summary",
                        capability_tags=["retrieval", "summarization"],
                        source_event_ids=[],
                    )
                ],
            )
        }
        self._event_ids = {"workspace_logistics_demo": []}
        self._events: dict[str, list[ExternalEvent]] = {"workspace_logistics_demo": []}
        self._step_responses: dict[str, list[AgentStepResponse]] = {"workspace_logistics_demo": []}
        self._initial_states = deepcopy(self._states)
        self._initial_histories = deepcopy(self._histories)
        self._initial_event_ids = deepcopy(self._event_ids)
        self._initial_events = deepcopy(self._events)
        self._initial_step_responses = deepcopy(self._step_responses)

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            yield

    def get_user_profile(self, user_id: str) -> UserProfile:
        with self._lock:
            return deepcopy(_lookup(self._users, "user", user_id))

    def get_environment_profile(self, environment_id: str) -> EnvironmentProfile:
        with self._lock:
            return deepcopy(_lookup(self._environments, "environment", environment_id))

    def get_workspace_state(self, workspace_id: str) -> WorkspaceState:
        with self._lock:
            return deepcopy(_lookup(self._states, "workspace", workspace_id))

    def set_workspace_state(self, workspace_state: WorkspaceState) -> None:
        with self._lock:
            self._states[workspace_state.workspace_id] = deepcopy(workspace_state)

    def get_historical_tasks(self, workspace_id: str) -> HistoricalTasks:
        with self._lock:
            return deepcopy(_lookup(self._histories, "workspace", workspace_id))

    def list_event_ids(self, workspace_id: str) -> list[str]:
        with self._lock:
            return list(self._event_ids.get(workspace_id, []))

    def list_events(self, workspace_id: str) -> list[ExternalEvent]:
        with self._lock:
            return deepcopy(self._events.get(workspace_id, []))

    def list_step_responses(self, workspace_id: str) -> list[AgentStepResponse]:
        with self._lock:
            return deepcopy(self._step_responses.get(workspace_id, []))

    def append_event(self, workspace_id: str, event: ExternalEvent) -> None:
        with self._lock:
            event_ids = self._event_ids.setdefault(workspace_id, [])
            if event.event_id not in event_ids:
                event_ids.append(event.event_id)
                self._events.setdefault(workspace_id, []).append(deepcopy(event))

    def append_step_response(self, workspace_id: str, response: AgentStepResponse) -> None:
        with self._lock:
            steps = self._step_responses.setdefault(workspace_id, [])
            existing_event_ids = {step.external_event.event_id for step in steps}
            if response.external_event.event_id not in existing_event_ids:
                steps.append(deepcopy(response))

    def next_event_index(self, workspace_id: str) -> int:
        with self._lock:
            return len(self._event_ids.get(workspace_id, [])) + 1

    def append_generated_tasks(
        self,
        workspace_id: str,
        opportunities: list[TaskOpportunity | dict],
    ) -> None:
        with self._lock:
            history = self._histories[workspace_id]
            existing_task_ids = {item.task_id for item in history.items}
            for opportunity in opportunities:
                data = (
                    opportunity.model_dump()
                    if isinstance(opportunity, TaskOpportunity)
                    else opportunity
                )
                task_id = f"task_from_{data['opportunity_id']}"
                if task_id in existing_task_ids:
                    continue
                history.items.append(
                    TaskHistoryItem(
                        task_id=task_id,
                        task_type=data["task_type"],
                        capability_tags=list(data.get("capability_tags", [])),
                        source_event_ids=[data["source_event_id"]],
                    )
                )
                existing_task_ids.add(task_id)

    def reset_workspace(self, workspace_id: str) -> None:
        with self._lock:
            if workspace_id not in self._initial_states:
                raise StoreResourceNotFound("workspace", workspace_id)
            self._states[workspace_id] = deepcopy(self._initial_states[workspace_id])
            self._histories[workspace_id] = deepcopy(self._initial_histories[workspace_id])
            self._event_ids[workspace_id] = deepcopy(self._initial_event_ids[workspace_id])
            self._events[workspace_id] = deepcopy(self._initial_events[workspace_id])
            self._step_responses[workspace_id] = deepcopy(self._initial_step_responses[workspace_id])
