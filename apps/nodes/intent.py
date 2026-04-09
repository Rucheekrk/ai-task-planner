from apps.llm import call_llm
from apps.logger import get_logger
from apps.state import AgentState

# Initialize logger for this node
logger = get_logger("IntentNode")


def intent_classification_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)  # separator for each new node run
    logger.info("Running Intent Classifier Node")

    # Prompt: classify input into task_planning or unclear
    prompt = f"""
You are an intent classifier for an AI task planning system.

Your job is to classify the user's input into exactly one of these categories:

- task_planning
- unclear

You must return only one label.

### Intent Definitions

task_planning:
Use this when the input contains ANY actionable content, planning intent, or task-like information.

This includes:
- goals, plans, or future actions
- notes, reminders, or to-do items
- long paragraphs describing work or next steps
- meeting notes or transcripts
- multiple sentences describing things to be done
- narrative or roadmap-style text
- any input that contains at least one actionable task or next step

IMPORTANT:
- Even if the input is long, messy, or written in paragraph form, classify as task_planning if it contains any actionable content.
- Do not require the input to look like a clean task list.

Examples:

Input: "I need to update my resume and apply to jobs."
Output:
task_planning

Input: "Next, I’ll continue testing edge cases. After that, I’ll improve input handling and then build an API."
Output:
task_planning

Input: "In the meeting, I will send the document, Priya will prepare the summary, and we need to schedule a follow-up."
Output:
task_planning

Input: "Here are my notes: finish slides, email professor, prepare for Friday meeting."
Output:
task_planning

Input: "I want to improve my career."
Output:
task_planning


unclear:
Use this ONLY when the input is truly unusable and contains no actionable planning content.

This includes:
- extremely vague input with no direction
- very short meaningless input
- random or broken text
- pure informational questions with no action intent

Examples:

Input: "Help me with this."
Output:
unclear

Input: "I don't know."
Output:
unclear

Input: "Something is wrong."
Output:
unclear

Input: "asdf random text"
Output:
unclear

Input: "What is Jira used for?"
Output:
unclear


### Decision Rules
- If there is ANY actionable content anywhere in the input → choose task_planning
- If the input contains even one task, next step, or goal → choose task_planning
- Choose unclear ONLY if there is absolutely no actionable or planning-related content
- When in doubt, strongly prefer task_planning

### Output Rules
- Return only one label
- Do not include explanations or extra text
- Do not include punctuation

Return exactly one of:
task_planning
unclear

### User Input
{state["raw_input"]}
"""

    # LLM Call: classify intent
    try:
        result = call_llm(prompt)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["intent"] = "unclear"
        return state

    # Validation: normalize and enforce valid intent
    intent = result.strip().lower()

    valid_intents = {"task_planning", "unclear"}

    if intent not in valid_intents:
        logger.warning(f"Unexpected intent output: {intent}. Defaulting to 'unclear'.")
        intent = "unclear"

    # State Update: store intent
    state["intent"] = intent

    logger.info(f"Detected intent: {intent}")

    return state