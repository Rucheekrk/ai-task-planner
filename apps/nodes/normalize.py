from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.normalize.prompt import get_normalize_prompt
from apps.utils.abbreviations import expand_abbreviations

# Initialize logger for this node
logger = get_logger("NORMALIZE")

def task_normalize_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    # Log entry into normalize node and raw input for debugging
    logger.info("Running Normalize Task Node")
    # logger.info(f"Normalize raw_input: {state.get('raw_input')}")

    # Retrieve extracted tasks from state
    tasks = state.get("tasks", [])

    # Handle case where no tasks were extracted
    if not tasks:
        logger.info("No extracted tasks found. Setting normalized_events to empty list.")
        state["normalized_events"] = []
        return dict(state)
    
    # Static abbreviation expansion: replace known abbreviations before LLM sees the tasks
    expanded_tasks = [
        {**task, "task": expand_abbreviations(task.get("task", ""))}
        for task in tasks
    ]

    # Prompt: Instruct LLM to extract additional information for task event. Normalize and classify tasks
    prompt = get_normalize_prompt(
        raw_input = state.get("raw_input", ""),
        tasks = expanded_tasks
    )

    # Call LLM to generate normalized structured events
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["normalized_events"] = []
        return dict(state)
    
    # Extract normalized events from LLM response
    normalized_events = result.get("normalized_events", [])

    # Validate that normalized events is a list
    if not isinstance(normalized_events, list):
        logger.warning("Invalid normalized_events format from LLM, defaulting to empty list")
        normalized_events = []

    # Define allowed values for event type and confidence
    allowed_event_types = {
        "new_task",
        "task_update",
        "status_change",
        "blocker",
        "dependency",
        "owner_change",
        "deadline_change",
    }

    allowed_confidence = {"high", "medium", "low"}

    # Clean and normalize each event object
    cleaned_events = []

    for item in normalized_events:
        if not isinstance(item, dict):
            continue
        
        event_type = item.get("event_type")
        task_text = item.get("task_text")
        owner = item.get("owner")
        status = item.get("status")
        deadline = item.get("deadline")
        blocker = item.get("blocker")
        dependency = item.get("dependency")
        confidence = item.get("confidence")

        # Validate and correct event_type if invalid
        if event_type not in allowed_event_types:
            logger.warning(f"Invalid event_type '{event_type}' found. Defaulting to 'new_task'")
            event_type = "new_task"

        # Skip invalid or empty task_text entries
        if not isinstance(task_text, str) or not task_text.strip():
            logger.warning("Skipping normalized event because task_text is missing or invalid")
            continue

        # Validate and correct confidence value
        if confidence not in allowed_confidence:
            logger.warning(f"Invalid confidence '{confidence}' found. Defaulting to 'medium'")
            confidence = "medium"

        # Append cleaned and normalized event to final list
        cleaned_events.append({
            "event_type": event_type,
            "task_text": task_text.strip(),
            "owner": owner if isinstance(owner, str) and owner.strip() else None,
            "status": status if isinstance(status, str) and status.strip() else None,
            "deadline": deadline if isinstance(deadline, str) and deadline.strip() else None,
            "blocker": blocker if isinstance(blocker, str) and blocker.strip() else None,
            "dependency": dependency if isinstance(dependency, str) and dependency.strip() else None,
            "confidence": confidence
        })

    # Store normalized events back into state
    state["normalized_events"] = cleaned_events

    # Log number of successfully normalized events
    logger.info(f"Normalized {len(cleaned_events)} task events")

    return dict(state)