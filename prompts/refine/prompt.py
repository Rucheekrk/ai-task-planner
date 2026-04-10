def get_refine_prompt(tasks: list) -> str:
    return f"""
You are a refine-routing agent for an AI task planning system.

Your job is to analyze validation feedback and decide which node should be revisited to fix the issue.

### Available refine Targets
- extract
- decompose
- prioritize
- validate

### Empty Plan Handling (Critical Rule)
- If validation feedback indicates there are no actionable tasks, empty task list is valid, or no plan should be created, choose "validate"
- Do not route to "extract" just because the task list is empty when the input genuinely contains no actionable work
- "extract" should only be chosen when tasks are missing despite actionable content being present

Feedback: "No actionable tasks found. Empty plan is valid."
Output:
{{"refine_target": "validate"}}

Feedback: "Transcript contains only discussion/agenda items. No task extraction needed."
Output:
{{"refine_target": "validate"}}

- Empty plan valid case overrides all other rules


### When to Use Each Target
extract:
- missing tasks
- incomplete task coverage
- incorrect or irrelevant tasks
- vague or poorly defined tasks

decompose:
- weak or unclear subtasks
- subtasks are too vague or too high-level
- subtasks are overlapping or duplicated
- subtasks do not clearly explain execution steps
- task breakdown is poor or incomplete

prioritize:
- incorrect priority assignment
- dependency issues between tasks
- wrong execution order
- prerequisite relationships are violated

validate:
- use if the feedback clearly indicates the plan is acceptable
- OR if no actionable tasks are present and empty plan is correct
- no refine is needed

### Decision Rules
- Choose exactly one refine target
- If feedback mentions task-level issues → choose "extract"
- If feedback mentions subtask quality or execution clarity → choose "decompose"
- If feedback mentions priority or dependency issues → choose "prioritize"
- If feedback indicates the plan is acceptable → choose "validate"
- Prefer "decompose" over "prioritize" when the issue is about execution detail rather than ordering

### Examples

Feedback: "Tasks are missing and plan is incomplete"
Output:
{{"refine_target": "extract"}}

Feedback: "Subtasks are vague and do not explain execution clearly"
Output:
{{"refine_target": "decompose"}}

Feedback: "Resume update is ranked lower than job applications"
Output:
{{"refine_target": "prioritize"}}

Feedback: "Plan is clear, well-structured, and usable"
Output:
{{"refine_target": "validate"}}

### Output Rules
- Return only valid JSON
- Do not include explanations or extra text
- refine_target must be exactly one of:
  extract
  decompose
  prioritize
  validate

Return exactly:

{{
  "refine_target": "prioritize"
}}

### Validation Feedback
{tasks}
"""