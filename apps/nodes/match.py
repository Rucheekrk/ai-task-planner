from apps.logger import get_logger
from apps.state import AgentState
from apps.db.db import fetch_active_tasks
from apps.db.db import fetch_semantic_task_match
from difflib import SequenceMatcher
import re

# Initialize logger
logger = get_logger("MATCH")


def normalize_text(text: str) -> str:
    # Normalize text for matching (lowercase + remove punctuation)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def similarity(a: str, b: str) -> float:
    # Compute string similarity score
    return SequenceMatcher(None, a, b).ratio()


def task_match_node(state: AgentState) -> AgentState:
    # Entry log
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Match Node")

    normalized_events = state.get("normalized_events", [])
    project_id = state.get("project_id", "default")

    # Fetch existing tasks scoped to this project
    existing_tasks = fetch_active_tasks(project_id)

    matched_events = []

    for event in normalized_events:
        task_text = event.get("task_text", "")
        event_type = event.get("event_type", "").strip().lower()

        # True for update events → must match existing task, False for new_task → can create new task 
        force_match = event_type != "new_task"

        # Default match fields for every event
        event["is_matched"] = False
        event["matched_task_id"] = None
        event["matched_task_text"] = None
        event["match_method"] = None
        event["match_confidence"] = "low"

        # Skip matching if task text is empty
        if not task_text:
            matched_events.append(event)
            continue

        norm_event_text = normalize_text(task_text)

        best_match = None
        best_score = 0.0
        match_method = None
        match_confidence = "low"

        # Step 1: Exact text match
        for task in existing_tasks:
            existing_task_text = task.get("task_text", "").strip()
            norm_task_text = normalize_text(existing_task_text)

            if norm_event_text == norm_task_text:
                best_match = task
                best_score = 1.0
                match_method = "exact"
                match_confidence = "high"
                break
        
        # Step 2: Partial/contains match for update events
        if not best_match and force_match:
            for task in existing_tasks:
                existing_task_text = (task.get("task_text") or "").strip()
                norm_task_text = normalize_text(existing_task_text)

                if not norm_task_text:
                    continue

                if norm_event_text in norm_task_text or norm_task_text in norm_event_text:
                    best_match = task
                    best_score = 0.90
                    match_method = "partial"
                    match_confidence = "high"
                    break

        # Step 3: Fuzzy text match (only if no exact match)
        if not best_match:
            for task in existing_tasks:
                existing_task_text = task.get("task_text", "").strip()
                norm_task_text = normalize_text(existing_task_text)

                if not norm_task_text:
                    continue

                score = similarity(norm_event_text, norm_task_text)

                if score > best_score:
                    best_score = score
                    best_match = task

            # Apply different thresholds based on event type
            if best_match:
                if force_match and best_score >= 0.50:
                    # For update events → accept best match even with lower threshold, but not too low
                    match_method = "fuzzy"
                    match_confidence = "high" if best_score >= 0.80 else "low"
                elif not force_match and best_score >= 0.75:
                    # For new tasks → stricter threshold
                    match_method = "fuzzy"
                    match_confidence = "high" if best_score >= 0.85 else "medium"
                else:
                    best_match = None
        
        # Step 4: Semantic match using pgvector (only if no exact, partial or fuzzy match)
        if not best_match:
            semantic_match = fetch_semantic_task_match(task_text, project_id)

            if semantic_match:
                score = semantic_match.get("similarity_score", 0)

                logger.info(f"Semantic score for '{task_text}' = {score}")

                if score >= 0.55:
                    best_match = semantic_match
                    best_score = score
                    match_method = "semantic"

                    if score >= 0.85:
                        match_confidence = "high"
                    elif score >= 0.65:
                        match_confidence = "medium"
                    else:
                        match_confidence = "low"


        # Step 5: Final result assignment
        if best_match:
            matched_task_id =  best_match.get("task_id") # DB uses task_id as primary key

            event["is_matched"] = True
            event["matched_task_id"] = matched_task_id
            event["matched_task_text"] = best_match.get("task_text")
            event["match_method"] = match_method
            event["match_confidence"] = match_confidence
        
            logger.info(
                f"Matched event '{task_text}' -> task_id = {matched_task_id}"
                f" using {match_method} ({best_score: .2f})"
            )
        else:
            if force_match:
                # ❗ update event but no match found → mark unresolved
                event["is_matched"] = False
                event["match_method"] = "unresolved"
                event["match_confidence"] = "low"

                logger.warning(f"Unresolved update event: '{task_text}' (no matching task found)")
            else:
                # new task → allowed to create
                logger.info(f"No match found for event '{task_text}'")

        matched_events.append(event)

    # Split matched vs new events for downstream nodes
    state["matched_events"] = matched_events
    state["events_to_update"] = [event for event in matched_events if event.get("is_matched")]
    state["events_to_create"] = [event for event in matched_events if not event.get("is_matched")]

    # Unresolved events for downstream nodes
    state["unresolved_events"] = [
    event for event in matched_events if event.get("match_method") == "unresolved"
    ]
    
    logger.info(
        f"Match summary: total={len(matched_events)}, "
        f"matched={len(state['events_to_update'])}, "
        f"new={len(state['events_to_create'])}"
    )

    return state