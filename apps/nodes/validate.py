from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.validate.prompt import get_empty_plan_validate_prompt, get_quality_validate_prompt


# Initialize logger for this node
logger = get_logger("VALIDATE")

def task_validate_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Validate Node")
    # logger.info(f"Validator raw_input: {state.get('raw_input')}")

    # Increment iteration counter for loop control
    state["current_iteration"] += 1

    # Deterministic guard: handle empty task plans by checking source input
    if not state["tasks"] or not state["prioritized_tasks"]:
        source_input = state.get("raw_input", "")

        # Get prompt for empty plan check
        prompt = get_empty_plan_validate_prompt(
           source_input = source_input,
           tasks = state.get("prioritized_tasks", [])
        )

        try:
            result = call_llm_json(prompt)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")

            state["is_valid"] = False
            state["validation_feedback"] = (
                "Validation failed because the LLM response could not be processed."
            )

            return dict(state)

        is_valid = result.get("is_valid", False)
        validation_feedback = result.get("validation_feedback", "")

        if not isinstance(is_valid, bool):
            logger.warning("Invalid is_valid format from LLM, defaulting to False")
            is_valid = False

        if not isinstance(validation_feedback, str):
            logger.warning("Invalid validation_feedback format from LLM, defaulting to empty string")
            validation_feedback = ""

        state["is_valid"] = is_valid
        state["validation_feedback"] = validation_feedback.strip()

        logger.info(f"Validation result: is_valid={is_valid}")
        logger.info(f"Validation feedback: {state['validation_feedback']}")

        return dict(state)

    # Prompt: evaluate plan quality and decide if refinement is needed
    prompt = get_quality_validate_prompt(
        raw_input = state.get("raw_input", []),
        tasks = state.get("prioritized_tasks", [])
    )

    # LLM Call: evaluate plan validity
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")

        state["is_valid"] = False
        state["validation_feedback"] = (
            "Validation failed because the LLM response could not be processed."
        )

        return dict(state)

    # Validation: extract fields safely
    is_valid = result.get("is_valid", False)
    validation_feedback = result.get("validation_feedback", "")

    # Normalize boolean output
    if not isinstance(is_valid, bool):
        logger.warning("Invalid is_valid format from LLM, defaulting to False")
        is_valid = False

    # Normalize feedback output
    if not isinstance(validation_feedback, str):
        logger.warning("Invalid validation_feedback format from LLM, defaulting to empty string")
        validation_feedback = ""

    # State Update: store validation results
    state["is_valid"] = is_valid
    state["validation_feedback"] = validation_feedback.strip()

    logger.info(f"Validation result: is_valid={is_valid}")
    logger.info(f"Validation feedback: {state['validation_feedback']}")

    return dict(state)