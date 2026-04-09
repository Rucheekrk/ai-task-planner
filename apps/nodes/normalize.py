from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("NORMALIZE")

def task_normalize_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    # Log entry into normalize node and raw input for debugging
    logger.info("Running Normalize Task Node")
    # logger.info(f"Normalize raw_input: {state.get('raw_input')}")

    # Retrieve extracted tasks from state
    tasks = state.get("tasks", [])

    # Handle case where no tasks were extracted
    if not tasks:
        logger.info("No extracted tasks found. Setting normalized_events to empty list.")
        state["normalized_events"] = []
        return dict(state)
    
    # Prompt: Instruct LLM to extract additional information for task event. Normalize and classify tasks
    prompt = f"""
You are a task normalization and classification agent for an AI project manager system.

Your job is to take the extracted task candidates and the original meeting/project context,
then convert each extracted item into a structured task event.

### Input Description
You are given:
1. The original raw input
2. A list of extracted task candidates

Each extracted task candidate may be incomplete.
You must use the raw input to enrich the extracted tasks with relevant context.

### Goal
For each extracted task candidate:
- identify the correct event type
- normalize the task text
- extract relevant structured fields
- avoid hallucinating information that is not supported by the raw input

### Allowed event_type values
You must choose exactly one of these values for each item:
- new_task
- task_update
- status_change
- blocker
- dependency
- owner_change
- deadline_change

### Event Type Definitions

new_task:
- use when the extracted item represents a newly assigned or newly created actionable task
- this is the default for normal action items unless a more specific update type clearly applies

task_update:
- use only when the item refers to an update to an existing task, but it does not clearly fit status_change, blocker, dependency, owner_change, or deadline_change
- use this as a fallback bucket only when needed

status_change:
- use when the task status is explicitly mentioned or changed
- examples: in progress, completed, done, blocked, not started, on hold

blocker:
- use when the extracted item represents a blocking issue, obstacle, or something preventing progress
- examples: waiting for credentials, pending approval, environment is unstable, missing dependency

dependency:
- use when the extracted item explicitly depends on another task or another task must happen first
- examples: testing depends on deployment, task A must happen before task B

owner_change:
- use when ownership is newly assigned, changed, or reassigned
- examples: John will handle this, move this to Priya, Arjun will take this up

deadline_change:
- use when a due date or timing commitment is explicitly introduced or changed
- examples: by Friday, tomorrow EOD, next Monday, moved to Thursday

### Field Rules

For each item, return these fields:
- event_type
- task_text
- owner
- status
- deadline
- blocker
- dependency
- confidence

### Field Behavior Rules
- task_text:
  - should be short, clear, and normalized
  - remove unnecessary conversational wording
  - preserve the core task meaning
  - for update-style events (status_change, owner_change, deadline_change, blocker, dependency, task_update),
    task_text must refer to the underlying task being updated, not the full update sentence
  - remove wrapper phrases such as:
    "mark ... as completed"
    "this task is blocked because ..."
    "assign this to ..."
    "move this to ..."
    "complete ... by Friday"
  - examples:
    "Mark the resume update task as completed" -> task_text: "Update resume"
    "John will take over API integration" -> task_text: "API integration"
    "Testing is blocked due to missing credentials" -> task_text: "Testing"

- owner:
  - fill only if explicitly mentioned in the raw input
  - otherwise return null

- status:
  - fill only if clearly stated
  - examples: not_started, in_progress, completed, blocked, on_hold
  - otherwise return null

- deadline:
  - fill only if explicitly mentioned
  - preserve the original wording if exact date normalization is not possible
  - otherwise return null

- blocker:
  - fill only if there is an explicit blocking reason
  - otherwise return null

- dependency:
  - fill only if there is an explicit dependency relationship
  - otherwise return null

- confidence:
  - must be exactly one of:
    high
    medium
    low

### Important Rules
- Do not invent new event_type values
- Do not hallucinate owners, deadlines, statuses, blockers, or dependencies
- Use the raw input to enrich the extracted tasks, but only with clearly supported information
- Keep output strictly grounded in the input
- Return one normalized object for each extracted task candidate
- Preserve the number of extracted task candidates unless an item is completely invalid
- If an extracted item is actionable and normal task creation is the best fit, use "new_task"

### Interpretation Guidance
- A task can still be "new_task" even if it also has an owner or deadline
- Use owner, deadline, blocker, status, and dependency as supporting fields
- Only choose owner_change, deadline_change, status_change, blocker, or dependency when that is clearly the main event represented by the extracted item
- Since these extracted items already came from the task extractor, most normal action items will likely remain "new_task"

### Examples

Raw input:
"Mark the resume update task as completed."

Extracted task:
{{"task": "Mark the resume update task as completed", "confidence": "high"}}

Output:
{{
  "event_type": "status_change",
  "task_text": "Update resume",
  "owner": null,
  "status": "completed",
  "deadline": null,
  "blocker": null,
  "dependency": null,
  "confidence": "high"
}}

Raw input:
"Priya, can you please reach out to the vendor and get the API credentials by tomorrow EOD?"

Extracted task:
{{"task": "Reach out to vendor for API credentials", "confidence": "high"}}

Output:
{{
  "event_type": "new_task",
  "task_text": "Get API credentials from vendor",
  "owner": "Priya",
  "status": null,
  "deadline": "tomorrow EOD",
  "blocker": null,
  "dependency": null,
  "confidence": "high"
}}

Raw input:
"John mentioned that he is currently working on the API integration for the payments module. However, the work is currently blocked because the credentials from the third-party vendor have not been received yet."

Extracted task:
{{"task": "API integration is blocked due to missing vendor credentials", "confidence": "high"}}

Output:
{{
  "event_type": "blocker",
  "task_text": "API integration for payments module",
  "owner": "John",
  "status": "blocked",
  "deadline": null,
  "blocker": "vendor credentials not received",
  "dependency": null,
  "confidence": "high"
}}

Raw input:
"Karan mentioned that he is still in progress and expects to complete it by next Monday."

Extracted task:
{{"task": "Analytics module work in progress", "confidence": "medium"}}

Output:
{{
  "event_type": "status_change",
  "task_text": "Complete analytics module work",
  "owner": "Karan",
  "status": "in_progress",
  "deadline": "next Monday",
  "blocker": null,
  "dependency": null,
  "confidence": "medium"
}}

Raw input:
"Testing cannot begin until deployment is completed."

Extracted task:
{{"task": "Testing depends on deployment", "confidence": "high"}}

Output:
{{
  "event_type": "dependency",
  "task_text": "Begin QA testing",
  "owner": null,
  "status": null,
  "deadline": null,
  "blocker": null,
  "dependency": "Testing depends on deployment completion",
  "confidence": "high"
}}

### Output Rules
- Return only valid JSON
- Do not include explanations or extra text
- Return exactly this structure:

{{
  "normalized_events": [
    {{
      "event_type": "new_task",
      "task_text": "example task",
      "owner": null,
      "status": null,
      "deadline": null,
      "blocker": null,
      "dependency": null,
      "confidence": "high"
    }}
  ]
}}

### Raw Input
{state.get("raw_input", "")}

### Extracted Task Candidates
{tasks}
"""

    # Call LLM to generate normalized structured events
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["normalized_events"] = []
        return dict(state)
    
    # Extract normalized events from LLM response
    normalized_events = result.get("normalized_events", [])

    # Validate that normalized events is a list
    if not isinstance(normalized_events, list):
        logger.warning("Invalid normalized_events format from LLM, defaulting to empty list")
        normalized_events = []

    # Define allowed values for event type and confidence
    allowed_event_types = {
        "new_task",
        "task_update",
        "status_change",
        "blocker",
        "dependency",
        "owner_change",
        "deadline_change",
    }

    allowed_confidence = {"high", "medium", "low"}

    # Clean and normalize each event object
    cleaned_events = []

    for item in normalized_events:
        if not isinstance(item, dict):
            continue
        
        event_type = item.get("event_type")
        task_text = item.get("task_text")
        owner = item.get("owner")
        status = item.get("status")
        deadline = item.get("deadline")
        blocker = item.get("blocker")
        dependency = item.get("dependency")
        confidence = item.get("confidence")

        # Validate and correct event_type if invalid
        if event_type not in allowed_event_types:
            logger.warning(f"Invalid event_type '{event_type}' found. Defaulting to 'new_task'")
            event_type = "new_task"

        # Skip invalid or empty task_text entries
        if not isinstance(task_text, str) or not task_text.strip():
            logger.warning("Skipping normalized event because task_text is missing or invalid")
            continue

        # Validate and correct confidence value
        if confidence not in allowed_confidence:
            logger.warning(f"Invalid confidence '{confidence}' found. Defaulting to 'medium'")
            confidence = "medium"

        # Append cleaned and normalized event to final list
        cleaned_events.append({
            "event_type": event_type,
            "task_text": task_text.strip(),
            "owner": owner if isinstance(owner, str) and owner.strip() else None,
            "status": status if isinstance(status, str) and status.strip() else None,
            "deadline": deadline if isinstance(deadline, str) and deadline.strip() else None,
            "blocker": blocker if isinstance(blocker, str) and blocker.strip() else None,
            "dependency": dependency if isinstance(dependency, str) and dependency.strip() else None,
            "confidence": confidence
        })

    # Store normalized events back into state
    state["normalized_events"] = cleaned_events

    # Log number of successfully normalized events
    logger.info(f"Normalized {len(cleaned_events)} task events")

    return dict(state)