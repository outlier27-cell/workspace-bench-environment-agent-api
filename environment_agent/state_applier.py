from __future__ import annotations

from copy import deepcopy

from environment_agent.schemas import (
    ArtifactState,
    DependencyEdge,
    ExternalEvent,
    WorkUnitMutation,
    WorkspaceEvolutionPlan,
    WorkspaceState,
    WorkUnitState,
)


def apply_evolution_plan(
    workspace_state: WorkspaceState,
    event: ExternalEvent,
    plan: WorkspaceEvolutionPlan,
) -> WorkspaceState:
    updated = deepcopy(workspace_state)
    is_replayed_event = event.event_id in updated.event_log
    artifact_by_id = {artifact.artifact_id: artifact for artifact in updated.artifacts}

    for mutation in plan.workunit_mutations:
        existing = next(
            (workunit for workunit in updated.active_work_units if workunit.workunit_id == mutation.workunit_id),
            None,
        )
        if existing is None and mutation.action == "create":
            updated.active_work_units.append(mutation_to_workunit_state(mutation, event.event_id))
        elif existing is not None:
            existing.status = mutation.resulting_status
            existing.priority = mutation.priority
            existing.related_entities = mutation.related_entities
            existing.deadline = mutation.deadline
            if event.event_id not in existing.source_event_ids:
                existing.source_event_ids.append(event.event_id)

    for item in plan.artifact_plan:
        if item.action in {"mark_stale", "archive"}:
            metadata = {
                "content_brief": item.content_brief,
                "action": item.action,
                "stale_of": item.stale_of,
            }
            if item.action == "archive":
                metadata["archived"] = True
            if item.artifact_id in artifact_by_id:
                stale_artifact = artifact_by_id[item.artifact_id]
                stale_artifact.path = item.path
                stale_artifact.artifact_type = item.artifact_type
                stale_artifact.role = item.role
                stale_artifact.workunit_id = item.workunit_id
                stale_artifact.is_stale = True
                stale_artifact.created_by_event_id = stale_artifact.created_by_event_id or event.event_id
                stale_artifact.metadata.update(metadata)
            else:
                new_stale_artifact = ArtifactState(
                    artifact_id=item.artifact_id,
                    path=item.path,
                    artifact_type=item.artifact_type,
                    role=item.role,
                    workunit_id=item.workunit_id,
                    is_stale=True,
                    created_by_event_id=event.event_id,
                    metadata=metadata,
                )
                updated.artifacts.append(new_stale_artifact)
                artifact_by_id[item.artifact_id] = new_stale_artifact
            continue

        if item.artifact_id in artifact_by_id:
            existing_artifact = artifact_by_id[item.artifact_id]
            existing_artifact.path = item.path
            existing_artifact.artifact_type = item.artifact_type
            existing_artifact.role = item.role
            existing_artifact.workunit_id = item.workunit_id
            if item.action != "reference":
                existing_artifact.is_stale = False
            existing_artifact.created_by_event_id = existing_artifact.created_by_event_id or event.event_id
            existing_artifact.metadata.update({"content_brief": item.content_brief, "action": item.action})
        else:
            new_artifact = ArtifactState(
                artifact_id=item.artifact_id,
                path=item.path,
                artifact_type=item.artifact_type,
                role=item.role,
                workunit_id=item.workunit_id,
                is_stale=False,
                created_by_event_id=event.event_id,
                metadata={"content_brief": item.content_brief, "action": item.action},
            )
            updated.artifacts.append(new_artifact)
            artifact_by_id[item.artifact_id] = new_artifact

    existing_edges = {
        (edge.source_artifact_id, edge.target_artifact_id, edge.relation): edge
        for edge in updated.dependency_edges
    }
    for edge in plan.dependency_mutations:
        key = (edge.source_artifact_id, edge.target_artifact_id, edge.relation)
        if edge.action == "add":
            if key in existing_edges:
                existing_edges[key].reason = edge.reason
                existing_edges[key].is_active = True
            else:
                new_edge = DependencyEdge(
                    source_artifact_id=edge.source_artifact_id,
                    target_artifact_id=edge.target_artifact_id,
                    relation=edge.relation,
                    reason=edge.reason,
                    is_active=True,
                )
                updated.dependency_edges.append(new_edge)
                existing_edges[key] = new_edge
        elif key in existing_edges:
            existing_edges[key].reason = edge.reason
            existing_edges[key].is_active = False

    if not is_replayed_event:
        updated.event_log.append(event.event_id)
        updated.current_snapshot_id = _next_snapshot_id(updated.current_snapshot_id)
    artifact_count = len(updated.artifacts)
    updated.metrics = {
        **updated.metrics,
        "active_work_units": len([wu for wu in updated.active_work_units if wu.status == "active"]),
        "artifact_family_count": artifact_count,
        "stale_file_ratio": (
            len([artifact for artifact in updated.artifacts if artifact.is_stale]) / artifact_count
            if artifact_count
            else 0.0
        ),
        "cross_workunit_edges": len(updated.dependency_edges),
    }
    return updated


def mutation_to_workunit_state(mutation: WorkUnitMutation, event_id: str) -> WorkUnitState:
    return WorkUnitState(
        workunit_id=mutation.workunit_id,
        title=mutation.title,
        status=mutation.resulting_status,
        priority=mutation.priority,
        related_entities=mutation.related_entities,
        deadline=mutation.deadline,
        source_event_ids=[event_id],
    )


def _next_snapshot_id(snapshot_id: str) -> str:
    prefix, separator, number = snapshot_id.rpartition("_")
    if separator and number.isdigit():
        return f"{prefix}_{int(number) + 1:04d}"
    return f"{snapshot_id}_0001"
