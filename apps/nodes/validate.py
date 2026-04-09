from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("ValidateNode")

def task_validate_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Validate Node")
    # logger.info(f"Validator raw_input: {state.get('raw_input')}")

    # Increment iteration counter for loop control
    state["current_iteration"] += 1

    # Deterministic guard: handle empty task plans by checking source input
    if not state["tasks"] or not state["prioritized_tasks"]:
        source_input = state.get("raw_input", "")

        prompt = f"""
You are a validate agent for an AI task planning system.

Your job is to evaluate whether the current prioritized task plan is good enough to move to final formatting, or whether it needs refinement.

### Input Description
- You are given the original source input and the current prioritized task plan
- Each task includes:
  - task
  - confidence
  - priority
  - subtasks

### Empty Plan Validation Rule (Critical Rule)
- You MUST examine the source input before deciding
- If the source input contains NO explicit actionable items (tasks, assignments, deadlines, owner-based actions, or follow-ups), then an empty plan is VALID
- Do NOT mark empty plans as invalid unless there is clear evidence of missed actionable tasks in the input
- If no actions exist, set is_valid = true

Input summary Example: "Team discussed roadmap ideas and shared updates. No decisions or assignments were made."
Plan: empty
Output:
{{"is_valid": true, "validation_feedback": "No actionable tasks are present in the input. Empty plan is valid."}}

Input summary Example: "John will prepare the budget by Friday and Priya will send the client update tomorrow."
Plan: empty
Output:
{{"is_valid": false, "validation_feedback": "Actionable tasks are present in the input but were not extracted. Extraction should be improved."}}

### Event-Aware Validation Rule (Critical)

- The system may produce both new tasks and update events (status_change, blocker, dependency, owner_change, deadline_change)
- Update events are valid outputs and must NOT be treated as missing tasks
- You must NOT expect every actionable statement to result in a new_task

- Only consider the plan invalid if:
  - clear, explicitly assigned new tasks (with owner and/or deadline) exist in the input
  - AND those new tasks are missing from the extracted output

- Do NOT mark the plan invalid due to:
  - presence of only update events
  - missing decomposition for update events
  - absence of new_task when input primarily contains updates

- If update events are correctly captured and no clear new tasks are missed, mark is_valid = true

### Validation Criteria
1. Tasks should be clear enough to be usable in a planning context
2. Tasks should not be duplicates or near-duplicates
3. Subtasks should clearly support the parent task
4. Priorities should be reasonable based on urgency, dependency, and execution order
5. The overall plan should be coherent, practical, and usable

### Important Interpretation Rule
- A parent task does not need to be extremely specific if it is still a valid planning goal
- Broad or high-level goals can be acceptable if the subtasks make the plan actionable
- Do not reject a plan only because the parent task is broad or abstract
- Reject the plan only if the overall plan is still too vague to execute

### Decision Rules
- For an empty plan, first determine whether the source input actually contains actionable tasks
- Mark is_valid = true if the source input contains no actionable tasks and the empty plan is appropriate
- Mark is_valid = false if actionable tasks clearly exist in the source input but were not extracted
- Keep feedback short, specific, and actionable
- Return only valid JSON

Return exactly:

{{
  "is_valid": true,
  "validation_feedback": "short feedback here"
}}

### Source Input
{source_input}

### Input Plan
{state["prioritized_tasks"]}
"""

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
    prompt = f"""
You are a validation agent for an AI task planning system.

Your job is to evaluate whether the current prioritized task plan is good enough to move to final formatting, or whether it needs refinement.

### Input Description
- You are given a prioritized task plan
- Each task includes:
  - task
  - confidence
  - priority
  - subtasks

### Empty Plan Validation Rule (Critical Rule)
- You MUST examine the source input before deciding
- If the source input contains NO explicit actionable items (tasks, assignments, deadlines, owner-based actions, or follow-ups), then an empty plan is VALID
- Do NOT mark empty plans as invalid unless there is clear evidence of missed actionable tasks in the input
- If no actions exist, set is_valid = true

Input summary Example: "Team discussed roadmap ideas and shared updates. No decisions or assignments were made."
Plan: empty
Output:
{{"is_valid": true, "feedback": "No actionable tasks are present in the input. Empty plan is valid."}}

Input summary Example: "John will prepare the budget by Friday and Priya will send the client update tomorrow."
Plan: empty
Output:
{{"is_valid": false, "feedback": "Actionable tasks are present in the input but were not extracted. Extraction should be improved."}}

### Validation Criteria
1. Tasks should be clear enough to be usable in a planning context
2. Tasks should not be duplicates or near-duplicates
3. Subtasks should clearly support the parent task
4. Priorities should be reasonable based on urgency, dependency, and execution order
5. The overall plan should be coherent, practical, and usable

### Important Interpretation Rule
- A parent task does not need to be extremely specific if it is still a valid planning goal
- Broad or high-level goals can be acceptable if the subtasks make the plan actionable
- Do not reject a plan only because the parent task is broad or abstract
- Reject the plan only if the overall plan is still too vague to execute

### Decision Rules
- Mark is_valid = true only if the plan is reasonably clear, consistent, and usable
- Mark is_valid = false if there are major issues that should be corrected
- Mark is_valid = false if a prerequisite task is ranked lower than a dependent task without strong reason
- Mark is_valid = false if subtasks are vague, too high-level, overlapping, or not actionable
- Mark is_valid = false if the plan remains impractical even after considering the subtasks
- Minor imperfections are acceptable if the plan is still usable

### Examples

Valid Plan Example:
Input:
[
  {{
    "task": "update resume",
    "priority": "high",
    "subtasks": ["revise summary", "add projects"]
  }},
  {{
    "task": "apply to jobs",
    "priority": "medium",
    "subtasks": ["search jobs", "submit applications"]
  }}
]

Output:
{{
  "is_valid": true,
  "validation_feedback": "Tasks are clear, well-structured, and priorities follow logical execution order."
}}

Valid Plan Example (broad goal with actionable subtasks):
Input:
[
  {{
    "task": "improve my career",
    "priority": "medium",
    "subtasks": [
      "identify skill gaps",
      "enroll in relevant courses",
      "network with industry professionals"
    ]
  }}
]

Output:
{{
  "is_valid": true,
  "validation_feedback": "The task is broad but the subtasks make the plan actionable and usable."
}}

Invalid Plan Example (dependency issue):
Input:
[
  {{
    "task": "apply to jobs",
    "priority": "high"
  }},
  {{
    "task": "update resume",
    "priority": "low"
  }}
]

Output:
{{
  "is_valid": false,
  "validation_feedback": "Resume update is a prerequisite and should not be lower priority than job applications."
}}

Invalid Plan Example (poor subtasks):
Input:
[
  {{
    "task": "prepare for interviews",
    "subtasks": ["work on it", "do practice"]
  }}
]

Output:
{{
  "is_valid": false,
  "validation_feedback": "Subtasks are vague and do not clearly explain how to execute the task."
}}

Invalid Plan Example (broad and still unusable):
Input:
[
  {{
    "task": "improve my career",
    "subtasks": ["work on it", "do better"]
  }}
]

Output:
{{
  "is_valid": false,
  "validation_feedback": "The plan is still too vague because the subtasks do not make the task actionable."
}}

### Feedback Rules
- If valid, explain briefly why the plan is acceptable
- If invalid, describe the main issue(s) clearly
- Keep feedback short, specific, and actionable

### Output Rules
- Return only valid JSON
- Do not include explanations or extra text

Return exactly:

{{
  "is_valid": true,
  "validation_feedback": "short feedback here"
}}

### Source Input
{state.get("raw_input", "")}

### Input Plan
{state["prioritized_tasks"]}
"""

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