from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.prioritize.prompt import get_prioritize_prompt

# Initialize logger for this node
logger = get_logger("PRIORITIZE")


def task_prioritize_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Prioritize Node")

    # Prompt: assign execution-aware priorities to tasks
    decomposed_tasks = state.get("decomposed_tasks", [])
    prompt = get_prioritize_prompt(tasks = decomposed_tasks)
    

    # LLM Call: get prioritized tasks from model
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")

        # ✅ Fallback: pass-through tasks (VERY IMPORTANT)
        state["prioritized_tasks"] = state.get("decomposed_tasks", [])
        return state

    # Validation: ensure correct top-level structure
    prioritized_tasks = result.get("prioritized_tasks", [])

    if not isinstance(prioritized_tasks, list) or len(prioritized_tasks) == 0:
        logger.warning("Invalid format or empty prioritized_tasks ouptut from LLM")
        state["prioritized_tasks"] = state.get("decomposed_tasks", [])
        return state

    # Normalization: clean and enforce schema consistency
    cleaned_prioritized_tasks = []
    valid_priorities = {"high", "medium", "low"}
    valid_confidence = {"high", "medium", "low"}

    for item in prioritized_tasks:
        if (
            isinstance(item, dict)
            and "task" in item
            and "subtasks" in item
            and "priority" in item
            and isinstance(item["subtasks"], list)
        ):
            task_text = item["task"].strip()

            # Enforce valid confidence values
            confidence = item.get("confidence", "medium")
            confidence = confidence.lower() if isinstance(confidence, str) else "medium"
            if confidence not in valid_confidence:
                confidence = "medium"

            # Enforce valid priority values
            priority = item.get("priority", "medium")
            priority = priority.lower() if isinstance(priority, str) else "medium"
            if priority not in valid_priorities:
                priority = "medium"

            # Clean subtasks list
            subtasks = [
                subtask.strip()
                for subtask in item["subtasks"]
                if isinstance(subtask, str) and subtask.strip()
            ]

            cleaned_prioritized_tasks.append({
                "task": task_text,
                "confidence": confidence,
                "priority": priority,
                "subtasks": subtasks
            })

    # State Update: store prioritized tasks
    state["prioritized_tasks"] = cleaned_prioritized_tasks

    logger.info(f"Prioritized {len(cleaned_prioritized_tasks)} tasks")

    return state