# Prompt for the prioritize node — instructs the LLM to assign high/medium/low priority
# to each task based on urgency, execution dependencies, and layer order.
# Core rule: prerequisite tasks must have equal or higher priority than the tasks they unblock.
def get_prioritize_prompt(tasks: str) -> str:
    return f"""
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
- high: urgent, foundational, time-sensitive, or blocking multiple important tasks
- medium: important but not foundational or not blocking multiple tasks
- low: useful but post-setup, optimization, or not blocking execution

### Core Principle
A task that is a prerequisite or dependency for another important task should usually have equal or higher priority than the task it enables.

### Dependency and Execution Rules
- If one task must be completed before another, prioritize the prerequisite equal or higher
- Tasks that unblock multiple downstream tasks should be prioritized as high
- Consider execution layers, not just strict sequence order
- Do not assign a dependent task higher priority than its prerequisite without strong reason
- Tasks that form the base system or core setup should be treated as foundational
- Tasks that are configuration, integration, or optimization after setup should be lower priority

### Layer-Based Priority Guidance
- High → foundational setup tasks that multiple other tasks depend on, OR tasks that must be completed before a final QA/testing step
- Medium → tasks that are important but do not block a final testing or verification step
- Low → final verification steps (QA testing, UAT, end-to-end testing, sign-off, stakeholder review) — these run last by design

### Final Step Rule (Critical)
- Tasks that are explicitly the final verification step before go-live (QA testing, UAT, end-to-end testing, acceptance testing, stakeholder sign-off) must ALWAYS be low priority
- These tasks run after all other work is done — being last does not make them high priority
- Any task that must be completed BEFORE the final QA/testing step should be high priority, because it blocks the final step

### Infrastructure Rule
- CI/CD pipelines, build systems, and deployment infrastructure are always high priority
- They are foundational — all development, testing, and integration work depends on them being in place

### Pre-QA Tasks Rule
- If a task must be completed before QA/end-to-end testing can begin, it should be high priority
- Examples: feature implementation, integration tasks, unit/integration tests — all must be done before QA runs

Example — Mobile App Launch:
Input:
[
  {{"task": "Set up CI/CD pipeline"}},
  {{"task": "Write unit tests for authentication module"}},
  {{"task": "Integrate payment gateway"}},
  {{"task": "Conduct end-to-end QA testing on staging"}}
]

Output:
[
  {{"task": "Set up CI/CD pipeline", "priority": "high"}},
  {{"task": "Write unit tests for authentication module", "priority": "high"}},
  {{"task": "Integrate payment gateway", "priority": "high"}},
  {{"task": "Conduct end-to-end QA testing on staging", "priority": "low"}}
]

Explanation: CI/CD is infrastructure. Auth tests and payment gateway must be done before QA can validate. QA is the final verification step — correctly low.

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
- Consider execution layers (foundation vs execution vs optimization)
- Do not rely only on strict sequence order
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
{tasks}
"""