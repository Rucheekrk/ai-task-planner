from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.decompose.prompt import get_decompose_prompt

# Initialize logger for this node
logger = get_logger("DECOMPOSE")


def task_decompose_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Decompose Node")

    # Filter only new_task events for decomposition
    events_to_create = state.get("events_to_create", [])

    tasks_to_decompose = [
        {
            "task": event["task_text"],
            "confidence": event.get("confidence", "medium")
        }
        for event in events_to_create
    ]

    # Handling new_task case: tasks_to_decompose is empty
    if not tasks_to_decompose:
        logger.info("No new_task events to decompose. Skipping decomposition.")
        state["decomposed_tasks"] = []
        return state

    # Prompt: instruct LLM to break tasks into actionable subtasks
    prompt = get_decompose_prompt(tasks = tasks_to_decompose)

    # LLM Call: get structured decomposition from model
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["decomposed_tasks"] = []
        return state

    # Validation: ensure correct top-level structure
    decomposed_tasks = result.get("decomposed_tasks", [])
    if not isinstance(decomposed_tasks, list):
        logger.warning("Invalid decomposed_tasks format from LLM, defaulting to empty list")
        decomposed_tasks = []

    # Normalization: clean and enforce schema consistency
    cleaned_decomposed_tasks = []
    valid_confidence = {"high", "medium", "low"}

    for item in decomposed_tasks:
        if (
            isinstance(item, dict)
            and "task" in item
            and "subtasks" in item
            and isinstance(item["subtasks"], list)
        ):
            task_text = item["task"].strip()

            # Enforce valid confidence values
            confidence = item.get("confidence", "medium")
            confidence = confidence.lower() if isinstance(confidence, str) else "medium"
            if confidence not in valid_confidence:
                confidence = "medium"

            # Keep only valid, non-empty subtasks
            subtasks = [
                subtask.strip()
                for subtask in item["subtasks"]
                if isinstance(subtask, str) and subtask.strip()
            ]

            cleaned_decomposed_tasks.append({
                "task": task_text,
                "confidence": confidence,
                "subtasks": subtasks
            })

    # State Update: store cleaned decomposition
    state["decomposed_tasks"] = cleaned_decomposed_tasks

    logger.info(f"Decomposed {len(cleaned_decomposed_tasks)} tasks")

    return state