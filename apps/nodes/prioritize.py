from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.prioritize.prompt import get_prioritize_prompt

# Initialize logger for this node
logger = get_logger("PRIORITIZE")


def task_prioritize_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)
    logger.info("Running Task Prioritize Node")

    # Build task list from both new and update events — both need priority assignment.
    # owner, deadline, blocker are passed as context so the LLM can make
    # execution-aware priority decisions (e.g. blocked tasks, imminent deadlines).
    events_to_create = state.get("events_to_create", [])
    events_to_update = state.get("events_to_update", [])

    tasks_to_prioritize = [
        {
            "task": event.get("task_text", ""),
            "owner": event.get("owner"),
            "deadline": event.get("deadline"),
            "blocker": event.get("blocker"),
            "confidence": event.get("confidence", "medium"),
        }
        for event in events_to_create + events_to_update
        if event.get("task_text")
    ]

    if not tasks_to_prioritize:
        logger.info("No tasks to prioritize. Skipping.")
        state["prioritized_tasks"] = []
        return state

    prompt = get_prioritize_prompt(tasks=tasks_to_prioritize)

    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        # Fallback: pass tasks through with default medium priority
        state["prioritized_tasks"] = [
            {"task": t["task"], "confidence": t["confidence"], "priority": "medium"}
            for t in tasks_to_prioritize
        ]
        return state

    prioritized_tasks = result.get("prioritized_tasks", [])

    if not isinstance(prioritized_tasks, list) or len(prioritized_tasks) == 0:
        logger.warning("Invalid or empty prioritized_tasks from LLM, using fallback")
        state["prioritized_tasks"] = [
            {"task": t["task"], "confidence": t["confidence"], "priority": "medium"}
            for t in tasks_to_prioritize
        ]
        return state

    valid_priorities = {"high", "medium", "low"}
    valid_confidence = {"high", "medium", "low"}
    cleaned = []

    for item in prioritized_tasks:
        if not isinstance(item, dict) or "task" not in item:
            continue

        task_text = item["task"].strip()

        confidence = item.get("confidence", "medium")
        confidence = confidence.lower() if isinstance(confidence, str) else "medium"
        if confidence not in valid_confidence:
            confidence = "medium"

        priority = item.get("priority", "medium")
        priority = priority.lower() if isinstance(priority, str) else "medium"
        if priority not in valid_priorities:
            priority = "medium"

        cleaned.append({
            "task": task_text,
            "confidence": confidence,
            "priority": priority,
        })

    state["prioritized_tasks"] = cleaned
    logger.info(f"Prioritized {len(cleaned)} tasks")
    return state
