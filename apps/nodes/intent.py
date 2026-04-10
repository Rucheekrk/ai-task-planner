from apps.llm import call_llm
from apps.logger import get_logger
from apps.state import AgentState
from prompts.intent.prompt import get_intent_prompt

# Initialize logger for this node
logger = get_logger("INTENT")


def intent_classification_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Intent Classifier Node")

    # Prompt: classify input into task_planning or unclear
    prompt = get_intent_prompt(raw_input = state.get("raw_input", ""))


    # LLM Call: classify intent
    try:
        result = call_llm(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["intent"] = "unclear"
        return state

    # Validation: normalize and enforce valid intent
    intent = result.strip().lower()

    valid_intents = {"task_planning", "unclear"}

    if intent not in valid_intents:
        logger.warning(f"Unexpected intent output: {intent}. Defaulting to 'unclear'.")
        intent = "unclear"

    # State Update: store intent
    state["intent"] = intent

    logger.info(f"Detected intent: {intent}")

    return state