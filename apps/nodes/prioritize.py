from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("PrioritizeNode")


def task_prioritize_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Prioritize Node")

    # Prompt: assign execution-aware priorities to tasks
    prompt = f"""
You are a task prioritize agent for an AI task planning system.

Your job is to assign a priority to each task in a practical and execution-aware way.

### Input Description
- You are given a list of tasks
- Each task includes:
  - task
  - confidence
  - subtasks

### Priority Labels
Use only:
- high
- medium
- low

### Priority Meaning
- high: urgent, foundational, time-sensitive, or blocking other important work
- medium: important but not immediately urgent or blocking
- low: useful but lower urgency or lower impact

### Core Principle
A task that is a prerequisite or dependency for another important task should usually have equal or higher priority than the task it enables.

### Dependency and Execution Rules
- If one task must be completed before another, prioritize the prerequisite equal or higher
- Tasks that unblock other important tasks should be prioritized higher
- Consider real execution order, not just perceived importance
- Do not assign a dependent task higher priority than its prerequisite without strong reason
- Tasks that affect readiness or quality for another task are foundational

Examples:
Input:
[
  {{"task": "update resume"}},
  {{"task": "apply to jobs"}}
]

Output:
[
  {{"task": "update resume", "priority": "high"}},
  {{"task": "apply to jobs", "priority": "medium"}}
]

Explanation: applying depends on having an updated resume

### Job Search Rule
- "update resume" is usually foundational for "apply to jobs"
- do not rank "update resume" below "apply to jobs" unless clearly justified

Example:
Input:
[
  {{"task": "prepare for interviews"}},
  {{"task": "update resume"}}
]

Output:
[
  {{"task": "update resume", "priority": "high"}},
  {{"task": "prepare for interviews", "priority": "medium"}}
]

### General Guidelines
- Consider urgency
- Consider dependencies
- Consider what unlocks other tasks
- Consider real-world execution order
- Do not invent new tasks or subtasks

### Consistency Rules
- Preserve the original "task"
- Preserve the original "confidence"
- Preserve the original "subtasks"

### Output Rules
- Return only valid JSON
- Do not include explanations or extra text

Return exactly:

{{
  "prioritized_tasks": [
    {{
      "task": "original task",
      "confidence": "high",
      "priority": "high",
      "subtasks": ["subtask 1", "subtask 2"]
    }}
  ]
}}

### Input Tasks
{state["decomposed_tasks"]}
"""

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