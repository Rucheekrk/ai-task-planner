from apps.logger import get_logger
from apps.state import AgentState
from apps.db.db import (
    insert_task,
    insert_event,
    update_task_field,
    update_task_subtasks,
    fetch_task_by_normalized_text,
    fetch_semantic_task_match,
    log_unresolved_event,
    upsert_source_document,
)
import re

# Initialize logger for this node
logger = get_logger("FORMAT")


def task_format_node(state: AgentState) -> AgentState:
    # Log entry into final formatter node
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Final Format Node")

    # Store new tasks in DB and apply updates before preparing final output
    store_tasks(state)
    store_events(state)
    apply_task_updates(state)
    log_unresolved_events(state)

    # Convert prioritized tasks into clean final output format
    formatted_tasks = []

    for item in state["prioritized_tasks"]:
        if isinstance(item, dict):
            task_text = item.get("task", "").strip()

            # Normalize priority value
            priority = item.get("priority", "medium")
            priority = priority.lower() if isinstance(priority, str) else "medium"
            if priority not in {"high", "medium", "low"}:
                priority = "medium"

            # Clean subtasks list
            subtasks = [
                subtask.strip()
                for subtask in item.get("subtasks", [])
                if isinstance(subtask, str) and subtask.strip()
            ]

            formatted_tasks.append({
                "task": task_text,
                "priority": priority,
                "subtasks": subtasks
            })

    # Clear refine target after successful completion
    state["refine_target"] = ""

    # Summarise unresolved events for the agent (strip source_doc_id — UUID reference not useful at agent level)
    unresolved_summary = [
        {k: v for k, v in event.items() if k != "source_doc_id"}
        for event in state.get("unresolved_events", [])
    ]

    # Expose non-new_task matched events so the agent can react to event types (blocker, deadline_change, etc.)
    # Strip source_doc_id — UUID reference not useful at the agent level
    event_signals = [
        {k: v for k, v in event.items() if k != "source_doc_id"}
        for event in state.get("matched_events", [])
        if event.get("event_type") not in ("new_task", None)
    ]

    # Summarise validation outcome for the agent
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 5)
    validation_outcome = {
        "passed": state.get("is_valid", False),
        "iterations": current_iteration,
        "hit_max_iterations": current_iteration >= max_iterations,
        "final_feedback": state.get("validation_feedback", ""),
    }

    # Prepare final output payload
    state["final_output"] = {
        "tasks_count": len(formatted_tasks),
        "tasks": formatted_tasks,
        "event_signals": event_signals,
        "unresolved_events": unresolved_summary,
        "validation_outcome": validation_outcome,
        "status": "completed",
    }

    logger.info(f"Final output prepared with {len(formatted_tasks)} tasks, "
                f"{len(unresolved_summary)} unresolved events, "
                f"validation passed={validation_outcome['passed']}")

    return state


def normalize_text(text: str) -> str:
    # Normalize text for DB storage consistency
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def _refresh_task(task_id, task_data: dict):
    # Re-apply priority and subtasks on an existing task found via dedup.
    # Keeps the task's enriched fields current without creating a duplicate row.
    if task_data.get("priority"):
        update_task_field(task_id, "priority", task_data["priority"])
    if task_data.get("subtasks") is not None:
        update_task_subtasks(task_id, task_data["subtasks"])


def store_tasks(state: AgentState):
    logger.info(f"store_tasks called. events_to_create count = {len(state.get('events_to_create', []))}")
    events_to_create = state.get("events_to_create", [])
    project_id = state.get("project_id", "default")

    # Build lookup from prioritized_tasks by normalized task text
    priority_lookup = {
        normalize_text(item.get("task", "")): item
        for item in state.get("prioritized_tasks", [])
        if isinstance(item, dict) and item.get("task")
    }

    for event in events_to_create:
        if event.get("event_type") == "new_task" and not event.get("is_matched"):
            norm_text = normalize_text(event.get("task_text", ""))
            enriched = priority_lookup.get(norm_text, {})

            task_data = {
                "task_text": event.get("task_text"),
                "normalized_task_text": norm_text,
                "owner": event.get("owner"),
                "status": event.get("status") or "not_started",
                "deadline": event.get("deadline"),
                "blocker": event.get("blocker"),
                "priority": enriched.get("priority", "medium"),
                "subtasks": enriched.get("subtasks", []),
            }

            # Deduplication guard — exact normalized text match (scoped to project)
            existing_task_id = fetch_task_by_normalized_text(norm_text, project_id)
            if existing_task_id:
                logger.info(f"Dedup (exact): task already exists (task_id={existing_task_id}), skipping insert for '{task_data['task_text']}'")
                event["matched_task_id"] = existing_task_id
                event["is_matched"] = True
                event["matched_task_text"] = event.get("task_text")
                event["match_method"] = "dedup"
                event["match_confidence"] = "high"
                _refresh_task(existing_task_id, task_data)
                continue

            # Deduplication guard — semantic similarity fallback (scoped to project)
            semantic_match = fetch_semantic_task_match(task_data["task_text"], project_id)
            if semantic_match and semantic_match.get("similarity_score", 0) >= 0.55:
                existing_task_id = semantic_match["task_id"]
                score = semantic_match["similarity_score"]
                logger.info(f"Dedup (semantic {score:.2f}): task already exists (task_id={existing_task_id}), skipping insert for '{task_data['task_text']}'")
                event["matched_task_id"] = existing_task_id
                event["is_matched"] = True
                event["matched_task_text"] = semantic_match.get("task_text")
                event["match_method"] = "dedup_semantic"
                event["match_confidence"] = "high" if score >= 0.85 else "medium"
                _refresh_task(existing_task_id, task_data)
                continue

            logger.info(f"Attempting to insert new task: {task_data['task_text']}")
            try:
                task_id = insert_task(task_data, project_id)
                logger.info(f"Inserted task successfully: {task_id}")
            except Exception as e:
                logger.error(f"Task insert failed for '{task_data['task_text']}': {e}")
                continue

            event["matched_task_id"] = task_id
            event["is_matched"] = True
            event["matched_task_text"] = event.get("task_text")
            event["match_method"] = "created"  # explicitly mark as newly created task
            event["match_confidence"] = "high"  # new tasks are always high confidence


def store_events(state: AgentState):
    # Insert all matched events into task_events history table.
    # The source document is stored once in source_documents and all events
    # reference it via source_doc_id — not by duplicating the full text per row.
    matched_events = state.get("matched_events", [])
    raw_input = state.get("raw_input", "")

    if not matched_events:
        return

    doc_id = upsert_source_document(raw_input)

    for event in matched_events:
        event["source_doc_id"] = doc_id
        insert_event(event)


def apply_task_updates(state: AgentState):
    # Apply updates to existing matched tasks based on event type
    matched_events = state.get("matched_events", [])

    # Build lookup from prioritized_tasks by normalized task text
    priority_lookup = {
        normalize_text(item.get("task", "")): item
        for item in state.get("prioritized_tasks", [])
        if isinstance(item, dict) and item.get("task")
    }

    for event in matched_events:
        task_id = event.get("matched_task_id")
        event_type = event.get("event_type")

        # Skip events that are not linked to a task record
        if not task_id:
            continue

        # Update status for status_change events
        if event_type == "status_change" and event.get("status"):
            update_task_field(task_id, "status", event.get("status"))

        # Update deadline for deadline_change events
        elif event_type == "deadline_change" and event.get("deadline"):
            update_task_field(task_id, "deadline", event.get("deadline"))

        # Update owner for owner_change events
        elif event_type == "owner_change" and event.get("owner"):
            update_task_field(task_id, "owner", event.get("owner"))

        # Update blocker and mark task status as blocked for blocker events
        elif event_type == "blocker":
            update_task_field(task_id, "blocker", event.get("blocker"))
            update_task_field(task_id, "status", event.get("status"))

        # Generic update: write any populated fields (owner, deadline, status, blocker)
        elif event_type == "task_update":
            for field in ("owner", "deadline", "status", "blocker"):
                if event.get(field):
                    update_task_field(task_id, field, event.get(field))

        # Always re-write priority and subtasks for matched tasks (enriched fields)
        norm_text = normalize_text(event.get("task_text", ""))
        enriched = priority_lookup.get(norm_text, {})

        if enriched.get("priority"):
            update_task_field(task_id, "priority", enriched["priority"])

        if enriched.get("subtasks") is not None:
            update_task_subtasks(task_id, enriched["subtasks"])


def log_unresolved_events(state: AgentState):
    # Write unresolved events to the unresolved_events review queue — no task is created.
    # These events failed all 4 match stages and require human review before any action is taken.
    unresolved_events = state.get("unresolved_events", [])

    if not unresolved_events:
        return

    raw_input = state.get("raw_input", "")

    for event in unresolved_events:
        task_text = event.get("task_text", "").strip()
        if not task_text:
            continue

        try:
            log_unresolved_event(event, source_input=raw_input)
            logger.warning(f"Unresolved event logged for review: '{task_text}' (type={event.get('event_type')})")
        except Exception as e:
            logger.error(f"Failed to log unresolved event '{task_text}': {e}")