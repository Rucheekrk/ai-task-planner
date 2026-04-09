from apps.logger import get_logger
from apps.state import AgentState
from apps.db.db import fetch_active_tasks
from apps.utils.embeddings import get_embedding
from difflib import SequenceMatcher
import re
import math

# Initialize logger
logger = get_logger("MatchNode")


def normalize_text(text: str) -> str:
    # Normalize text for matching (lowercase + remove punctuation)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def similarity(a: str, b: str) -> float:
    # Compute string similarity score
    return SequenceMatcher(None, a, b).ratio()

def cosine_similarity(vec1: list, vec2: list) -> float:
    # Compute cosine similarity between two embedding vectors
    if not vec1 or not vec2:
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_vec1 = math.sqrt(sum(a * a for a in vec1))
    norm_vec2 = math.sqrt(sum(b * b for b in vec2))

    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0.0
    
    return dot_product / (norm_vec1 * norm_vec2)


def task_match_node(state: AgentState) -> AgentState:
    # Entry log
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Match Node")

    normalized_events = state.get("normalized_events", [])

    # Fetch existing tasks from the database
    existing_tasks = fetch_active_tasks()

    matched_events = []

    for event in normalized_events:
        task_text = event.get("task_text", "")
        event_type = event.get("event_type", "").strip().lower()

        # True for update events → must match existing task, False for new_task → can create new task 
        force_match = event_type != "new_task"

        # Default match fields for every event
        event["is_matched"] = False
        event["matched_task_id"] = None
        event["matched_task_test"] = None
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
                    match_confidence = "medium" if best_score >= 0.80 else "low"
                elif not force_match and best_score >= 0.75:
                    # For new tasks → stricter threshold
                    match_method = "fuzzy"
                    match_confidence = "high" if best_score >= 0.85 else "medium"
                else:
                    best_match = None
        
        # Step 4: Semantic match using embeddings (only if no exact/fuzzy match)
        if not best_match:
            event_embedding = get_embedding(task_text)

            if event_embedding:
                for task in existing_tasks:
                    task_embedding = task.get("task_embedding")

                    if not task_embedding:
                        continue

                    score = cosine_similarity(event_embedding, task_embedding)

                    if score > best_score:
                        best_score = score
                        best_match = task

                # Threshold for semantic match
                if best_match:
                    if force_match and best_score >= 0.60:
                        match_method = "semantic"
                        match_confidence = "medium" if best_score < 0.80 else "high"
                    elif not force_match and best_score >= 0.80:
                        match_method = "semantic"
                        match_confidence = "high" if best_score >= 0.90 else "medium"
                    else:
                        best_match = None

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
            logger.info(f"No match found for event '{task_text}'")

        matched_events.append(event)

    # Split matched vs new events for downstream nodes
    state["matched_events"] = matched_events
    state["events_to_update"] = [event for event in matched_events if event.get("is_matched")]
    state["events_to_create"] = [event for event in matched_events if not event.get("is_matched")]

    logger.info(
        f"Match summary: total={len(matched_events)}, "
        f"matched={len(state['events_to_update'])}, "
        f"new={len(state['events_to_create'])}"
    )

    return state