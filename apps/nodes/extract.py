from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("EXTRACT")


def task_extract_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Task Extract Node")

    # Prompt: instruct LLM to extract tasks conservatively from input
    prompt = f"""
You are a task extraction agent for an AI task planning system.

Your job is to extract task candidates from the user's input.

The input may be:
- a short request
- messy notes
- a long planning paragraph
- meeting notes
- a meeting transcript
- a long document containing discussions, decisions, and next steps

Your output must be conservative but recall-oriented:
- extract only tasks that are explicitly stated or strongly supported by the input
- do not invent tasks that are not supported
- do not miss valid task-like content just because it appears inside long narrative text
- scan the full input carefully and extract all supported task candidates

### Core Objective
Extract tasks that a person could reasonably act on.

For long-form or transcript-like input, extract tasks wherever they appear in the text, not just at the beginning.

### Definition of a Task
A task is:
- a clear unit of work someone can act on
- specific enough to be meaningful
- not broken down into smaller subtasks at this stage

For transcript-style input, a task may appear as:
- a direct action item
- an assignment
- a commitment
- a follow-up
- a next step
- a planning-related goal that is clearly intended for future action

### Agenda vs Action Distinction
Not all sentences that contain action verbs represent real tasks.

Do NOT extract tasks from:
- meeting agendas
- presentation flow descriptions
- informational statements about what will be discussed
- statements describing what "the board", "the team", or "we" will present, review, discuss, or update as part of a meeting
- phrases like:
  - "we will discuss"
  - "we will provide an update"
  - "we will review"
  - "the board will discuss"
  - "there will be an update on"
  - "the purpose of today's meeting is to discuss"

These are NOT tasks because they do not represent actionable work items assigned for execution.

Examples of NOT tasks:

Input: "We will provide an update on finance and budget issues."
Output:
[]

Input: "The board will discuss the annual Action Plan."
Output:
[]

Input: "We will give a brief organizational update."
Output:
[]

Input: "We will discuss recommendation status changes."
Output:
[]

These describe meeting flow, not actionable work.

Extract tasks ONLY when there is clear execution intent such as:
- assignments
- commitments
- follow-ups
- requests for action
- next steps

Examples of VALID tasks:

Input: "I will send the report tomorrow."
Output:
[
  {{"task": "send the report", "confidence": "high"}}
]

Input: "Rucheek will prepare the demo."
Output:
[
  {{"task": "prepare the demo", "confidence": "high"}}
]

Input: "We need to confirm the budget with finance."
Output:
[
  {{"task": "confirm budget with finance", "confidence": "high"}}
]

Input: "Please submit comments via email."
Output:
[
  {{"task": "submit comments via email", "confidence": "high"}}
]

### When No Tasks Exist (CRITICAL RULE)
It is completely valid for the input to contain NO actionable tasks.

If the input only contains:
- meeting descriptions
- agenda items
- informational content
- presentation flow
- discussion topics

Then you MUST return:

{{
  "tasks": []
}}

Do NOT attempt to infer or generate tasks from such content.

Do NOT create tasks just because the input contains action words like:
- "discuss"
- "review"
- "provide update"

These are often part of meeting narration, not execution work.

If no real actionable tasks exist, you must return an empty list even if the input contains many action verbs or meeting agenda statements.

Do not try harder to find tasks when none exist.

Returning an empty list is the correct behavior when no real tasks are present.

### What to Extract
Extract task candidates when the input contains:
- explicit action statements
- assigned work
- future commitments
- next-step language
- follow-up requests
- planning-oriented goals
- task-like shorthand notes
- only actions that represent real work to be executed, not discussion or presentation topics

Examples of extractable transcript/task language:
- "I'll send the updated deck tomorrow"
- "Rucheek will prepare the demo"
- "We need to confirm the budget with finance"
- "Let's schedule a follow-up next week"
- "Next step is to add file upload support"
- "finish slides, email professor, prepare for Friday meeting"

### What Not to Extract
Do not extract:
- general discussion with no action
- background information
- opinions with no next step
- summaries with no actionable item
- vague ideas that are not clearly intended as work
- speculative tasks that are not supported by the input
- optional participation instructions or public meeting instructions unless the input clearly frames them as actual tasks to be completed

Examples of non-task content:
- "The current workflow seems inefficient"
- "This feature is interesting"
- "We discussed several possible options"
- "The budget has been tight this quarter"

These are not tasks unless the text also includes a clear action such as:
- "Review the workflow"
- "Evaluate the feature"
- "Choose one option"
- "Confirm budget with finance"

### Granularity Rules
- Extract tasks at a medium level
- Do not decompose tasks into execution steps
- Do not merge clearly separate actions into one task
- Do not expand one vague goal into several specific tasks

Examples:
Input: "Prepare for interviews"
Output:
[
  {{"task": "prepare for interviews", "confidence": "high"}}
]

Input: "Update resume and apply to jobs"
Output:
[
  {{"task": "update resume", "confidence": "high"}},
  {{"task": "apply to jobs", "confidence": "high"}}
]

Input: "I need to prepare for interviews"
Not allowed output:
[
  {{"task": "practice coding questions", "confidence": "medium"}},
  {{"task": "schedule mock interviews", "confidence": "medium"}},
  {{"task": "revise DSA", "confidence": "medium"}}
]

### Long-Form and Transcript Rules
- Read the full input, not just the opening lines
- Extract tasks from anywhere in the input if they are supported
- If multiple task candidates appear across the text, extract each distinct one
- Preserve broad planning goals as one task when that is all the input supports
- For transcript-like input, include explicit commitments and follow-ups as tasks
- Do not require the text to look like a to-do list in order to extract tasks

Examples:
Input: "Next, I’ll continue testing with more edge cases. After that, I’ll add better input handling like multi-line input and file uploads, and then start building a simple interface."
Output:
[
  {{"task": "continue testing edge cases", "confidence": "high"}},
  {{"task": "add better input handling", "confidence": "high"}},
  {{"task": "start building a simple interface", "confidence": "high"}}
]

Input: "In the meeting, we agreed that I would send the document, Priya would prepare the summary, and we need to schedule a follow-up call."
Output:
[
  {{"task": "send the document", "confidence": "high"}},
  {{"task": "prepare the summary", "confidence": "high"}},
  {{"task": "schedule a follow-up call", "confidence": "high"}}
]

### Vague Input Handling
- If the input contains only one broad goal, extract at most one high-level task
- If the goal is too vague to support multiple distinct tasks, preserve it as a single task
- Do not fabricate planning steps from a vague goal
- Return an empty list only if there is no usable task-like content at all

Examples:
Input: "I need to get fit this month."
Output:
[
  {{"task": "get fit this month", "confidence": "high"}}
]

Input: "I want to improve my career."
Output:
[
  {{"task": "improve my career", "confidence": "high"}}
]

Not allowed output for the above:
[
  {{"task": "update resume", "confidence": "medium"}},
  {{"task": "apply to jobs", "confidence": "medium"}},
  {{"task": "network on LinkedIn", "confidence": "medium"}}
]

Input: "What is AI?"
Output:
[]

Input: "Can you explain how Jira works?"
Output:
[]

### Inclusion Rules
- Include only tasks that are explicitly stated or strongly supported by the input
- If the user mentions multiple distinct actions, extract each as a separate task
- If the input is partially structured, normalize the wording into clean task labels
- For transcript-like input, include explicit assignments, commitments, and follow-ups

Examples:
Input: "resume update, job apply, interview prep"
Output:
[
  {{"task": "update resume", "confidence": "high"}},
  {{"task": "apply to jobs", "confidence": "high"}},
  {{"task": "prepare for interviews", "confidence": "high"}}
]

Input: "Need to finish presentation and send the email"
Output:
[
  {{"task": "finish presentation", "confidence": "high"}},
  {{"task": "send email", "confidence": "high"}}
]

### Exclusion Rules
- Do not add new tasks that are not present in the input
- Do not include explanations, commentary, assumptions, or reasoning
- Do not include duplicates or near-duplicates
- Do not produce subtasks in this node
- Do not over-infer hidden intentions
- Do not convert every meeting topic into a task unless it clearly implies action

Examples:
Input: "I need to apply for jobs"
Not allowed output:
[
  {{"task": "apply to jobs", "confidence": "high"}},
  {{"task": "update resume", "confidence": "medium"}},
  {{"task": "network on LinkedIn", "confidence": "medium"}}
]

Input: "We discussed hiring timelines and product strategy"
Output:
[]

Input: "Update resume and resume review"
Preferred output:
[
  {{"task": "update resume", "confidence": "high"}}
]

### Quality Rules
- Rewrite tasks to be concise and readable
- Preserve the user's meaning
- Start with an action-oriented phrase when reasonable
- Keep phrasing consistent across tasks

Examples:
Input phrase: "resume update"
Normalized task: "update resume"

Input phrase: "job applications"
Normalized task: "apply to jobs"

Input phrase: "interview prep"
Normalized task: "prepare for interviews"

Input phrase: "I’ll send the updated deck tomorrow"
Normalized task: "send the updated deck"

### Confidence Scoring
Use only these values:
- high
- medium
- low

Definitions:
- high = explicitly stated in the input
- medium = clearly implied by the input but not stated word-for-word
- low = weakly implied; avoid using low unless necessary

For transcript-like input:
- direct assignments and direct commitments are usually high
- clear follow-ups may be high or medium depending on wording
- weak inference should be avoided

Examples:
Input: "Update resume"
Output:
[
  {{"task": "update resume", "confidence": "high"}}
]

Input: "I should start applying soon"
Output:
[
  {{"task": "apply to jobs", "confidence": "medium"}}
]

Input: "We still need to confirm the vendor details"
Output:
[
  {{"task": "confirm vendor details", "confidence": "high"}}
]

### Output Rules
- Return only valid JSON
- Do not include markdown
- Do not include code fences
- Do not include extra text before or after the JSON

Return exactly this schema:

{{
  "tasks": [
    {{
      "task": "task description",
      "confidence": "high"
    }}
  ]
}}

User input:
{state["raw_input"]}
"""

    # LLM Call: get structured task output from model
    try:
        result = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["tasks"] = []
        return state

    # Validation: ensure tasks is a list
    tasks = result.get("tasks", [])
    if not isinstance(tasks, list):
        logger.warning("Invalid tasks format from LLM, defaulting to empty list")
        tasks = []

    # Normalization: clean tasks and enforce schema consistency
    cleaned_tasks = []
    valid_confidence = {"high", "medium", "low"}

    for item in tasks:
        if isinstance(item, dict) and "task" in item:
            task_text = item["task"].strip()

            # Enforce valid confidence values
            confidence = item.get("confidence", "medium")
            confidence = confidence.lower() if isinstance(confidence, str) else "medium"

            if confidence not in valid_confidence:
                confidence = "medium"

            cleaned_tasks.append({
                "task": task_text,
                "confidence": confidence
            })

    # State Update: store cleaned tasks in graph state
    state["tasks"] = cleaned_tasks

    logger.info(f"Extracted {len(cleaned_tasks)} tasks")

    return state