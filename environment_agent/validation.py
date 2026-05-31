from __future__ import annotations

from environment_agent.schemas import (
    AgentStepRequest,
    PlannedEnvironmentStep,
    PlanValidationReport,
)


class PlanValidationError(ValueError):
    def __init__(self, report: PlanValidationReport) -> None:
        self.report = report
        super().__init__("; ".join(report.errors))


def validate_planned_step(
    request: AgentStepRequest,
    planned_step: PlannedEnvironmentStep,
) -> PlanValidationReport:
    checks = [
        "event_links",
        "workunit_references",
        "artifact_references",
        "dependency_references",
        "task_references",
    ]
    errors: list[str] = []
    warnings: list[str] = []

    event = planned_step.external_event
    plan = planned_step.evolution_plan
    workspace = request.workspace_state
    workspace_workunit_ids = {workunit.workunit_id for workunit in workspace.active_work_units}
    created_workunit_ids = {
        mutation.workunit_id for mutation in plan.workunit_mutations if mutation.action == "create"
    }
    valid_workunit_ids = workspace_workunit_ids | created_workunit_ids

    if plan.source_event_id != event.event_id:
        errors.append(
            f"evolution_plan.source_event_id '{plan.source_event_id}' does not match event '{event.event_id}'"
        )

    for constraint in planned_step.constraints:
        if constraint.applies_to_event_id != event.event_id:
            errors.append(
                f"constraint '{constraint.constraint_id}' applies to '{constraint.applies_to_event_id}' "
                f"instead of event '{event.event_id}'"
            )

    for opportunity in planned_step.task_opportunities:
        if opportunity.source_event_id != event.event_id:
            errors.append(
                f"task opportunity '{opportunity.opportunity_id}' points to source event "
                f"'{opportunity.source_event_id}' instead of '{event.event_id}'"
            )

    for target_workunit_id in event.target_workunit_ids:
        if target_workunit_id not in valid_workunit_ids:
            errors.append(
                f"event target workunit '{target_workunit_id}' is not present in workspace or plan mutations"
            )

    for mutation in plan.workunit_mutations:
        if mutation.action != "create" and mutation.workunit_id not in workspace_workunit_ids:
            errors.append(
                f"workunit mutation '{mutation.workunit_id}' uses action '{mutation.action}' "
                "for a workunit not currently present in workspace state"
            )

    workspace_artifact_ids = {artifact.artifact_id for artifact in workspace.artifacts}
    plan_artifact_ids = {item.artifact_id for item in plan.artifact_plan}
    valid_artifact_ids = workspace_artifact_ids | plan_artifact_ids
    active_dependency_edges = {
        (edge.source_artifact_id, edge.target_artifact_id, edge.relation)
        for edge in workspace.dependency_edges
        if edge.is_active
    }

    for item in plan.artifact_plan:
        if item.workunit_id not in valid_workunit_ids:
            errors.append(
                f"artifact '{item.artifact_id}' references unknown workunit '{item.workunit_id}'"
            )
        if item.action == "reference" and item.artifact_id not in workspace_artifact_ids:
            errors.append(
                f"artifact '{item.artifact_id}' uses reference action but is not present in workspace state"
            )
        for dependency_id in item.depends_on:
            if dependency_id not in valid_artifact_ids:
                errors.append(
                    f"artifact '{item.artifact_id}' depends on unknown artifact '{dependency_id}'"
                )
        if item.stale_of is not None and item.stale_of not in valid_artifact_ids:
            errors.append(
                f"artifact '{item.artifact_id}' marks stale_of unknown artifact '{item.stale_of}'"
            )

    for dependency in plan.dependency_mutations:
        if dependency.source_artifact_id not in valid_artifact_ids:
            errors.append(
                f"dependency source '{dependency.source_artifact_id}' is not in workspace or artifact plan"
            )
        if dependency.target_artifact_id not in valid_artifact_ids:
            errors.append(
                f"dependency target '{dependency.target_artifact_id}' is not in workspace or artifact plan"
            )
        if dependency.action in {"remove", "mark_stale"}:
            key = (
                dependency.source_artifact_id,
                dependency.target_artifact_id,
                dependency.relation,
            )
            if key not in active_dependency_edges:
                errors.append(
                    f"dependency '{dependency.source_artifact_id}' -> "
                    f"'{dependency.target_artifact_id}' relation '{dependency.relation}' "
                    "is not currently active in workspace state"
                )

    for opportunity in planned_step.task_opportunities:
        for artifact_id in opportunity.required_artifact_ids:
            if artifact_id not in valid_artifact_ids:
                errors.append(
                    f"task opportunity '{opportunity.opportunity_id}' requires unknown artifact '{artifact_id}'"
                )

    return PlanValidationReport(
        status="failed" if errors else "passed",
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


def raise_if_invalid(report: PlanValidationReport) -> None:
    if report.errors:
        raise PlanValidationError(report)
