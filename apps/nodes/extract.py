from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.extract.prompt import get_extract_prompt

# Initialize logger for this node
logger = get_logger("EXTRACT")


def task_extract_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Extract Node")

    # Prompt: instruct LLM to extract tasks conservatively from input
    prompt = get_extract_prompt(raw_input = state.get("raw_input", ""))

    # LLM Call: get structured task output from model
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["tasks"] = []
        return state

    # Validation: ensure tasks is a list
    tasks = result.get("tasks", [])
    if not isinstance(tasks, list):
        logger.warning("Invalid tasks format from LLM, defaulting to empty list")
        tasks = []

    # Normalization: clean tasks and enforce schema consistency
    cleaned_tasks = []
    valid_confidence = {"high", "medium", "low"}

    for item in tasks:
        if isinstance(item, dict) and "task" in item:
            task_text = item["task"].strip()

            # Enforce valid confidence values
            confidence = item.get("confidence", "medium")
            confidence = confidence.lower() if isinstance(confidence, str) else "medium"

            if confidence not in valid_confidence:
                confidence = "medium"

            cleaned_tasks.append({
                "task": task_text,
                "confidence": confidence
            })

    # State Update: store cleaned tasks in graph state
    state["tasks"] = cleaned_tasks

    logger.info(f"Extracted {len(cleaned_tasks)} tasks")

    return state