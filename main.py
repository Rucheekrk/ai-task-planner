from apps.logger import get_logger
from apps.state import AgentState
from apps.graph import build_graph
import json
import sys

# Initialize logger for main entry
logger = get_logger("MAIN")


if __name__ == "__main__":
    # Build LangGraph pipeline
    graph = build_graph()

    # Multi-line User Input (double Enter to submit)
    print("Reading input from stdin... (use: python3 main.py < input.txt)\n")

    # Read full input stream (supports large transcripts)
    user_input = sys.stdin.read().strip()

    # # Optional: quick preview for debugging
    # print("--- INPUT PREVIEW ---")
    # print(user_input[:])
    # print("--- END PREVIEW ---\n")


    # Initial state: user_input + empty placeholders
    initial_state: AgentState = {
        "raw_input": user_input,
        "intent": "",
        "tasks": [],
        "normalized_events": [],
        "matched_events": [],
        "decomposed_tasks": [],
        "prioritized_tasks": [],
        "is_valid": False,
        "validation_feedback": "",
        "refine_target": "",
        "final_output": {},
        "max_iterations": 4,
        "current_iteration": 0,
    }

    # Execute graph
    final_state = graph.invoke(initial_state)

    # Logging: key pipeline outputs
    logger.info(f"Intent result: {final_state['intent']}")
    logger.info(f"Extracted tasks count: {len(final_state['tasks'])}")
    logger.info(f"Normalized tasks count: {len(final_state['normalized_events'])}")
    logger.info(f"Matched tasks count: {len(final_state['matched_events'])}")
    logger.info(f"Decomposed tasks count: {len(final_state['decomposed_tasks'])}")
    logger.info(f"Prioritized tasks count: {len(final_state['prioritized_tasks'])}")
    logger.info(f"Validation status: {final_state['is_valid']}")
    logger.info(f"Validation feedback: {final_state['validation_feedback']}")
    logger.info(f"refine target: {final_state['refine_target']}")
    logger.info(f"Final output status: {final_state['final_output'].get('status', '')}")

    # Output: full state for debugging
    print()
    print(json.dumps(final_state, indent=1))