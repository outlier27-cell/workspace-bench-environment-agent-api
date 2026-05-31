from environment_agent.mock_store import MockEnvironmentStore
from environment_agent.schemas import (
    AgentStepRequest,
    ArtifactPlanItem,
    DependencyMutation,
    ExternalEvent,
    PlannedEnvironmentStep,
    WorkUnitMutation,
    WorkspaceEvolutionPlan,
)
from environment_agent.validation import validate_planned_step


def test_validation_gate_rejects_non_create_unknown_workunit_mutation():
    store = MockEnvironmentStore()
    request = AgentStepRequest(
        user_profile=store.get_user_profile("user_logistics_001"),
        environment_profile=store.get_environment_profile("env_peak_logistics"),
        workspace_state=store.get_workspace_state("workspace_logistics_demo"),
        historical_tasks=store.get_historical_tasks("workspace_logistics_demo"),
    )
    event = ExternalEvent(
        event_id="evt_unknown_workunit",
        event_type="incident",
        timestamp="2026-04-21T10:30:00",
        source_actor="customer",
        target_workunit_ids=["wu_missing"],
        trigger_reason="A backend tried to advance a missing workunit.",
        expected_workspace_effects=["advance missing workunit"],
        affected_entities=["customer_X"],
        difficulty_effects={"retrieval": "medium"},
    )
    plan = WorkspaceEvolutionPlan(
        plan_id="plan_unknown_workunit",
        source_event_id=event.event_id,
        workunit_mutations=[
            WorkUnitMutation(
                action="advance",
                workunit_id="wu_missing",
                title="Missing workunit",
                reason="This should not be accepted as an existing workunit.",
                resulting_status="active",
                priority="high",
            )
        ],
        artifact_plan=[
            ArtifactPlanItem(
                action="create",
                artifact_id="art_orphan",
                path="/bad/orphan.md",
                artifact_type="md",
                role="orphan",
                workunit_id="wu_missing",
                reason="This artifact would be orphaned if validation passed.",
                content_brief="orphan artifact",
            )
        ],
        dependency_mutations=[],
        snapshot_policy="snapshot_after_plan_application",
    )

    report = validate_planned_step(
        request,
        PlannedEnvironmentStep(
            external_event=event,
            constraints=[],
            evolution_plan=plan,
            task_opportunities=[],
        ),
    )

    assert report.status == "failed"
    assert any("wu_missing" in error for error in report.errors)


def test_validation_gate_rejects_reference_to_unknown_artifact():
    store = MockEnvironmentStore()
    request = AgentStepRequest(
        user_profile=store.get_user_profile("user_logistics_001"),
        environment_profile=store.get_environment_profile("env_peak_logistics"),
        workspace_state=store.get_workspace_state("workspace_logistics_demo"),
        historical_tasks=store.get_historical_tasks("workspace_logistics_demo"),
    )
    event = ExternalEvent(
        event_id="evt_bad_reference",
        event_type="incident",
        timestamp="2026-04-21T10:30:00",
        source_actor="customer",
        target_workunit_ids=["wu_weekly_ops"],
        trigger_reason="A backend referenced an artifact that is not in the workspace.",
        expected_workspace_effects=["reference missing artifact"],
        affected_entities=["customer_X"],
        difficulty_effects={"retrieval": "medium"},
    )
    plan = WorkspaceEvolutionPlan(
        plan_id="plan_bad_reference",
        source_event_id=event.event_id,
        workunit_mutations=[],
        artifact_plan=[
            ArtifactPlanItem(
                action="reference",
                artifact_id="art_missing_reference",
                path="/missing/reference.md",
                artifact_type="md",
                role="reference_only",
                workunit_id="wu_weekly_ops",
                reason="This should not create a new artifact.",
                content_brief="A reference to missing evidence.",
            )
        ],
        dependency_mutations=[],
        snapshot_policy="snapshot_after_plan_application",
    )

    report = validate_planned_step(
        request,
        PlannedEnvironmentStep(
            external_event=event,
            constraints=[],
            evolution_plan=plan,
            task_opportunities=[],
        ),
    )

    assert report.status == "failed"
    assert any("reference" in error and "art_missing_reference" in error for error in report.errors)


def test_validation_gate_rejects_removing_unknown_dependency_edge():
    store = MockEnvironmentStore()
    request = AgentStepRequest(
        user_profile=store.get_user_profile("user_logistics_001"),
        environment_profile=store.get_environment_profile("env_peak_logistics"),
        workspace_state=store.get_workspace_state("workspace_logistics_demo"),
        historical_tasks=store.get_historical_tasks("workspace_logistics_demo"),
    )
    event = ExternalEvent(
        event_id="evt_bad_dependency_remove",
        event_type="incident",
        timestamp="2026-04-21T10:30:00",
        source_actor="customer",
        target_workunit_ids=["wu_weekly_ops"],
        trigger_reason="A backend tried to remove a dependency edge that does not exist.",
        expected_workspace_effects=["remove missing dependency edge"],
        affected_entities=["customer_X"],
        difficulty_effects={"retrieval": "medium"},
    )
    plan = WorkspaceEvolutionPlan(
        plan_id="plan_bad_dependency_remove",
        source_event_id=event.event_id,
        workunit_mutations=[],
        artifact_plan=[],
        dependency_mutations=[
            DependencyMutation(
                action="remove",
                source_artifact_id="art_carrier_scorecard_q1",
                target_artifact_id="art_weekly_report_draft",
                relation="summarized_by",
                reason="This edge is not present in the workspace.",
            )
        ],
        snapshot_policy="snapshot_after_plan_application",
    )

    report = validate_planned_step(
        request,
        PlannedEnvironmentStep(
            external_event=event,
            constraints=[],
            evolution_plan=plan,
            task_opportunities=[],
        ),
    )

    assert report.status == "failed"
    assert any("dependency" in error and "not currently active" in error for error in report.errors)
