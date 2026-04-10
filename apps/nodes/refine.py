from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.refine.prompt import get_refine_prompt

# Initialize logger for this node
logger = get_logger("REFINE")


def task_refine_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Refine Router Node")

    # Prompt: decide which node to revisit based on validation feedback
    prompt = get_refine_prompt(tasks = state.get("validation_feedback", []))


    # LLM Call: determine refine target
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["refine_target"] = "prioritize"
        return state

    # Validation: normalize refine target
    refine_target = str(result.get("refine_target", "prioritize")).strip().lower()

    valid_targets = {"extract", "decompose", "prioritize", "validate"}
    if refine_target not in valid_targets:
        logger.warning(f"Invalid refine_target: {refine_target}. Defaulting to 'prioritize'")
        refine_target = "prioritize"

    # State Update: store routing decision
    state["refine_target"] = refine_target

    logger.info(f"refine target selected: {refine_target}")

    return state