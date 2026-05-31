from environment_agent.mock_store import MockEnvironmentStore
from environment_agent.schemas import (
    ArtifactPlanItem,
    DependencyMutation,
    ExternalEvent,
    WorkspaceEvolutionPlan,
    WorkspaceState,
)
from environment_agent.state_applier import apply_evolution_plan


def _event(event_id: str = "evt_manual_debug") -> ExternalEvent:
    return ExternalEvent(
        event_id=event_id,
        event_type="incident",
        timestamp="2026-04-21T10:30:00",
        source_actor="customer",
        target_workunit_ids=["wu_weekly_ops"],
        trigger_reason="Manual regression event.",
        expected_workspace_effects=["exercise state applier edge cases"],
        affected_entities=["customer_X"],
        difficulty_effects={"retrieval": "medium"},
    )


def _plan(
    artifact_plan: list[ArtifactPlanItem] | None = None,
    dependency_mutations: list[DependencyMutation] | None = None,
) -> WorkspaceEvolutionPlan:
    return WorkspaceEvolutionPlan(
        plan_id="plan_manual_debug",
        source_event_id="evt_manual_debug",
        workunit_mutations=[],
        artifact_plan=artifact_plan or [],
        dependency_mutations=dependency_mutations or [],
        snapshot_policy="snapshot_after_plan_application",
    )


def test_archive_artifact_action_marks_existing_artifact_stale():
    store = MockEnvironmentStore()
    state = store.get_workspace_state("workspace_logistics_demo")

    updated = apply_evolution_plan(
        state,
        _event(),
        _plan(
            artifact_plan=[
                ArtifactPlanItem(
                    action="archive",
                    artifact_id="art_sla_policy_q1",
                    path="/policies/sla_policy_q1.pdf",
                    artifact_type="pdf",
                    role="stale_policy_candidate",
                    workunit_id="wu_weekly_ops",
                    reason="The policy is superseded and should not be active evidence.",
                    content_brief="Archived Q1 SLA policy.",
                )
            ]
        ),
    )

    archived = next(artifact for artifact in updated.artifacts if artifact.artifact_id == "art_sla_policy_q1")
    assert archived.is_stale is True
    assert archived.metadata["action"] == "archive"
    assert archived.metadata["archived"] is True


def test_dependency_remove_and_mark_stale_actions_deactivate_existing_edges():
    store = MockEnvironmentStore()
    state = store.get_workspace_state("workspace_logistics_demo")

    removed = apply_evolution_plan(
        state,
        _event(),
        _plan(
            dependency_mutations=[
                DependencyMutation(
                    action="remove",
                    source_artifact_id="art_march_shipments",
                    target_artifact_id="art_weekly_report_draft",
                    relation="summarized_by",
                    reason="The weekly report no longer summarizes this source table.",
                )
            ]
        ),
    )
    assert removed.dependency_edges[0].is_active is False
    assert removed.dependency_edges[0].reason == "The weekly report no longer summarizes this source table."

    restaled = apply_evolution_plan(
        state,
        _event(),
        _plan(
            dependency_mutations=[
                DependencyMutation(
                    action="mark_stale",
                    source_artifact_id="art_march_shipments",
                    target_artifact_id="art_weekly_report_draft",
                    relation="summarized_by",
                    reason="The relationship is stale after a new source of truth arrived.",
                )
            ]
        ),
    )
    assert restaled.dependency_edges[0].is_active is False
    assert restaled.dependency_edges[0].reason == "The relationship is stale after a new source of truth arrived."


def test_apply_plan_handles_empty_artifact_workspace_metrics():
    state = WorkspaceState(
        workspace_id="empty_workspace",
        current_snapshot_id="snap_0001",
        active_work_units=[],
        artifacts=[],
        dependency_edges=[],
        event_log=[],
        metrics={},
    )

    updated = apply_evolution_plan(state, _event(), _plan())

    assert updated.metrics["artifact_family_count"] == 0
    assert updated.metrics["stale_file_ratio"] == 0.0


def test_apply_plan_advances_unstructured_snapshot_ids_without_crashing():
    store = MockEnvironmentStore()
    state = store.get_workspace_state("workspace_logistics_demo")
    state.current_snapshot_id = "snapshot-alpha"

    updated = apply_evolution_plan(state, _event(), _plan())

    assert updated.current_snapshot_id == "snapshot-alpha_0001"
