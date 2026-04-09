from apps.logger import get_logger
from apps.state import AgentState
from apps.db.db import (
    insert_task,
    insert_event,
    update_task_field
)
import re

# Initialize logger for this node
logger = get_logger("FinalFormatNode")


def task_format_node(state: AgentState) -> AgentState:
    # Log entry into final formatter node
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Final Format Node")

    # Store new tasks in DB and apply updates before preparing final output
    store_tasks(state)
    store_events(state)
    apply_task_updates(state)

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

    # Prepare final output payload
    state["final_output"] = {
        "intent": state["intent"],
        "tasks_count": len(formatted_tasks),
        "tasks": formatted_tasks,
        "status": "completed"
    }

    logger.info(f"Final output prepared with {len(formatted_tasks)} tasks")

    return state


def normalize_text(text: str) -> str:
    # Normalize text for DB storage consistency
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def store_tasks(state: AgentState):
    logger.info(f"store_tasks called. events_to_create count = {len(state.get('events_to_create', []))}")  # debug function entry
    # Insert only unmatched new tasks into tasks table
    events_to_create = state.get("events_to_create", [])

    for event in events_to_create:
        if event.get("event_type") == "new_task" and not event.get("is_matched"):
            task_data = {
                "task_text": event.get("task_text"),
                "normalized_task_text": normalize_text(event.get("task_text")),
                "owner": event.get("owner"),
                "status": event.get("status") or "not_started",
                "deadline": event.get("deadline"),
                "blocker": event.get("blocker"),
            }

            logger.info(f"Attempting to insert new task: {task_data['task_text']}")  # debug before insert

            # Insert new task and attach generated task_id back to event
            # task_id = insert_task(task_data)
            try:
                task_id = insert_task(task_data)
                logger.info(f"Inserted task successfully: {task_id}")  # debug after insert
            except Exception as e:
                logger.error(f"Task insert failed for '{task_data['task_text']}': {e}")  # debug insert failure
                continue

            event["matched_task_id"] = task_id
            event["is_matched"] = True
            event["matched_task_text"] = event.get("task_text")
            event["match_method"] = "created"  # explicitly mark as newly created task
            event["match_confidence"] = "high"  # new tasks are always high confidence


def store_events(state: AgentState):
    # Insert all matched events into task_events history table
    matched_events = state.get("matched_events", [])
    raw_input = state.get("raw_input", "")

    for event in matched_events:
        event["source_input"] = raw_input
        insert_event(event)


def apply_task_updates(state: AgentState):
    # Apply updates to existing matched tasks based on event type
    matched_events = state.get("matched_events", [])

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