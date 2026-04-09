from typing import TypedDict, List, Dict, Any


# Shared state passed across all LangGraph nodes
class AgentState(TypedDict):
    raw_input: str  # original user input
    intent: str  # classified intent (task_planning / unclear)

    tasks: List[Dict[str, Any]]  # extracted tasks
    normalized_events: List[Dict[str, Any]]  # structured task/event objects after normalization
    matched_events: List[Dict[str, Any]]  # normalized events enriched with task matching results
    events_to_update: List[Dict[str, Any]]  # matched events (existing tasks to update)
    events_to_create: List[Dict[str, Any]]  # new tasks (no match found)
    decomposed_tasks: List[Dict[str, Any]]  # tasks with subtasks
    prioritized_tasks: List[Dict[str, Any]]  # tasks with priority

    is_valid: bool  # validation result
    validation_feedback: str  # feedback from validator
    refine_target: str  # next node to revisit if invalid

    final_output: Dict[str, Any]  # formatted output for downstream use

    max_iterations: int  # loop limit for refinement
    current_iteration: int  # current iteration count