from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("DecomposeNode")


def task_decompose_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Decompose Node")

    # Filter only new_task events for decomposition
    events_to_create = state.get("events_to_create", [])

    tasks_to_decompose = [
        {
            "task": event["task_text"],
            "confidence": event.get("confidence", "medium")
        }
        for event in events_to_create
    ]

    # Handling new_task case: tasks_to_decompose is empty
    if not tasks_to_decompose:
        logger.info("No new_task events to decompose. Skipping decomposition.")
        state["decomposed_tasks"] = []
        return state

    # Prompt: instruct LLM to break tasks into actionable subtasks
    prompt = f"""
You are a task decompose agent for an AI task planning system.

Your job is to convert each input task into a small set of clear, actionable subtasks that help complete the original task.

### Input Description
- You are given a list of tasks
- Each task has:
  - "task": string
  - "confidence": string (high, medium, low)
- Tasks are already at a medium level of detail
- Your role is to break them into execution-level steps

### Definition of Subtasks
A subtask is:
- a specific, actionable step
- directly contributes to completing the parent task
- executable without further clarification

Examples:
Input task: "update resume"
Output subtasks:
[
  "revise summary section",
  "add recent projects",
  "update skills section"
]

Input task: "apply to jobs"
Output subtasks:
[
  "search for relevant job postings",
  "tailor resume for each job",
  "submit applications"
]

### Decomposition Rules
- Generate between 2 and 5 subtasks per task
- Each subtask should represent a single clear action
- Subtasks should be logically ordered where possible
- Maintain alignment with the original task
- Do not introduce unrelated goals
- Do not assume extra requirements that are not implied by the task

Example:
Input task: "prepare for interviews"
Output:
[
  "revise core concepts",
  "practice coding problems",
  "take mock interviews"
]

Not allowed:
[
  "update resume",
  "apply to jobs"
]

### Granularity Rules
- Do not repeat the original task as a subtask
- Do not keep subtasks too high-level
- Do not create overly small steps

Examples:
Input task: "update resume"

Too high-level (not allowed):
[
  "work on resume"
]

Too granular (not allowed):
[
  "open laptop",
  "open resume file",
  "start typing"
]

Good:
[
  "revise summary section",
  "add recent projects",
  "update skills section"
]

### Edge Cases
- If a task is already simple or atomic, generate 1 or 2 meaningful execution steps
- Keep decomposition minimal for already atomic tasks
- Do not force unnecessary decomposition
- Do not invent implied materials, attachments, approvals, or extra setup unless clearly supported by the task

Examples:
Input task: "send email"
Output:
[
  "draft email content",
  "send email"
]

Input task: "send email to the recruiter"
Good output:
[
  "draft email content",
  "send email"
]

Not preferred output:
[
  "draft email content",
  "add recipient's email address",
  "attach relevant documents",
  "send email"
]

### Quality Rules
- Use clear and concise language
- Start each subtask with an action verb
- Avoid duplication
- Ensure subtasks are distinct

### Consistency Rules
- Preserve the original "task" exactly as given
- Preserve the original "confidence" value
- Do not modify or infer a new confidence

### Output Rules
- Return only valid JSON
- Do not include explanations or extra text

Return exactly:

{{
  "decomposed_tasks": [
    {{
      "task": "original task",
      "confidence": "high",
      "subtasks": ["subtask 1", "subtask 2"]
    }}
  ]
}}

### Input Tasks
{tasks_to_decompose}
"""

    # LLM Call: get structured decomposition from model
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["decomposed_tasks"] = []
        return state

    # Validation: ensure correct top-level structure
    decomposed_tasks = result.get("decomposed_tasks", [])
    if not isinstance(decomposed_tasks, list):
        logger.warning("Invalid decomposed_tasks format from LLM, defaulting to empty list")
        decomposed_tasks = []

    # Normalization: clean and enforce schema consistency
    cleaned_decomposed_tasks = []
    valid_confidence = {"high", "medium", "low"}

    for item in decomposed_tasks:
        if (
            isinstance(item, dict)
            and "task" in item
            and "subtasks" in item
            and isinstance(item["subtasks"], list)
        ):
            task_text = item["task"].strip()

            # Enforce valid confidence values
            confidence = item.get("confidence", "medium")
            confidence = confidence.lower() if isinstance(confidence, str) else "medium"
            if confidence not in valid_confidence:
                confidence = "medium"

            # Keep only valid, non-empty subtasks
            subtasks = [
                subtask.strip()
                for subtask in item["subtasks"]
                if isinstance(subtask, str) and subtask.strip()
            ]

            cleaned_decomposed_tasks.append({
                "task": task_text,
                "confidence": confidence,
                "subtasks": subtasks
            })

    # State Update: store cleaned decomposition
    state["decomposed_tasks"] = cleaned_decomposed_tasks

    logger.info(f"Decomposed {len(cleaned_decomposed_tasks)} tasks")

    return state