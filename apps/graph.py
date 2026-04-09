from langgraph.graph import StateGraph, END

from apps.state import AgentState
from apps.nodes.intent import intent_classification_node
from apps.nodes.extract import task_extract_node
from apps.nodes.normalize import task_normalize_node
from apps.nodes.match import task_match_node
from apps.nodes.decompose import task_decompose_node
from apps.nodes.prioritize import task_prioritize_node
from apps.nodes.validate import task_validate_node
from apps.nodes.refine import task_refine_node
from apps.nodes.format import task_format_node


# Intent Router: decide next step after intent classification
def intent_router(state: AgentState) -> str:
    # Read intent from state with fallback to 'unclear'
    intent = state.get("intent", "unclear")

    # Validate intent value against allowed options
    valid_intents = {"task_planning", "unclear"}
    if intent not in valid_intents:
        intent = "unclear"

    return "extract" if intent == "task_planning" else "final"


# Validate Router: decide next step after validation
def validate_router(state: AgentState) -> str:
    # Stop if max iterations reached
    if state.get("current_iteration", 0) >= state.get("max_iterations", 4):
        return "final"

    # Route based on validation result
    return "final" if state.get("is_valid", False) else "refine"


# Refine Router: decide which node to revisit after refinement
def refine_router(state: AgentState) -> str:
    target = state.get("refine_target", "prioritize")

    valid_targets = {"extract", "decompose", "prioritize", "validate"}

    if target not in valid_targets:
        target = "prioritize"

    return target


def build_graph():
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("intent", intent_classification_node)
    graph.add_node("extract", task_extract_node)
    graph.add_node("normalize", task_normalize_node)
    graph.add_node("match", task_match_node)
    graph.add_node("decompose", task_decompose_node)
    graph.add_node("prioritize", task_prioritize_node)
    graph.add_node("validate", task_validate_node)
    graph.add_node("refine", task_refine_node)
    graph.add_node("final", task_format_node)

    # Entry point
    graph.set_entry_point("intent")

    # Intent routing
    graph.add_conditional_edges(
        "intent",
        intent_router,
        {
            "extract": "extract",
            "final": "final",
        },
    )

    # Main flow
    graph.add_edge("extract", "normalize")
    graph.add_edge("normalize", "match")
    graph.add_edge("match", "decompose")
    graph.add_edge("decompose", "prioritize")
    graph.add_edge("prioritize", "validate")

    # Validate routing
    graph.add_conditional_edges(
        "validate",
        validate_router,
        {
            "final": "final",
            "refine": "refine",
        },
    )

    # Refine routing
    graph.add_conditional_edges(
        "refine",
        refine_router,
        {
            "extract": "extract",
            "decompose": "decompose",
            "prioritize": "prioritize",
            "validate": "validate",
        },
    )

    # Final node
    graph.add_edge("final", END)

    return graph.compile()