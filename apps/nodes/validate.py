from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.validate.prompt import get_empty_plan_validate_prompt, get_quality_validate_prompt


# Initialize logger for this node
logger = get_logger("VALIDATE")


def _apply_validation_result(state: AgentState, result: dict) -> AgentState:
    """
    Shared helper: extract is_valid + validation_feedback from an LLM result dict,
    run loop detection, append to validation_history, and write back to state.
    Called from both the empty-plan path and the quality-validate path.
    """
    is_valid = result.get("is_valid", False)
    validation_feedback = result.get("validation_feedback", "")

    if not isinstance(is_valid, bool):
        logger.warning("Invalid is_valid format from LLM, defaulting to False")
        is_valid = False

    if not isinstance(validation_feedback, str):
        logger.warning("Invalid validation_feedback format from LLM, defaulting to empty string")
        validation_feedback = ""

    validation_feedback = validation_feedback.strip()

    # Loop detection: if feedback is identical to the last iteration the refine cycle
    # made no progress — accept the plan to break out rather than spinning indefinitely.
    validation_history = state.get("validation_history", [])
    if validation_history and validation_history[-1] == validation_feedback:
        logger.warning("Repeated validation feedback detected. Breaking refinement loop.")
        is_valid = True
        validation_feedback = "Plan accepted after repeated refinement. Minor issues remain but plan is usable."

    validation_history.append(validation_feedback)
    state["validation_history"] = validation_history
    state["is_valid"] = is_valid
    state["validation_feedback"] = validation_feedback

    logger.info(f"Validation result: is_valid={is_valid}")
    logger.info(f"Validation feedback: {validation_feedback}")

    return state


def task_validate_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)
    logger.info("Running Task Validate Node")

    # Increment iteration counter for loop control
    state["current_iteration"] += 1

    # Empty-plan path: task list is empty — ask LLM if that is correct given the source input
    if not state["tasks"] or not state["prioritized_tasks"]:
        prompt = get_empty_plan_validate_prompt(
            source_input=state.get("raw_input", ""),
            tasks=state.get("prioritized_tasks", [])
        )

        try:
            result = call_llm_json(prompt)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            state["is_valid"] = False
            state["validation_feedback"] = "Validation failed because the LLM response could not be processed."
            return dict(state)

        return dict(_apply_validation_result(state, result))

    # Quality-validate path: plan exists — evaluate quality and priority coherence
    prompt = get_quality_validate_prompt(
        raw_input=state.get("raw_input", ""),
        tasks=state.get("prioritized_tasks", [])
    )

    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["is_valid"] = False
        state["validation_feedback"] = "Validation failed because the LLM response could not be processed."
        return dict(state)

    return dict(_apply_validation_result(state, result))
