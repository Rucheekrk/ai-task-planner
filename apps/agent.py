import asyncio
import json
import os
from functools import lru_cache
from typing import Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from apps.graph import build_graph
from apps.logger import get_logger

load_dotenv()
logger = get_logger("AGENT")

# Maximum number of plan → execute → observe cycles before the agent stops.
# Keeps token cost and latency bounded — 3 iterations covers the common case
# of pipeline run + verification + one follow-up tool call.
MAX_REACT_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Pipeline wrapper
# ---------------------------------------------------------------------------

# Default blank state passed to the pipeline on every invocation.
# Each run gets a fresh copy so prior pipeline state never bleeds across agent calls.
PIPELINE_INITIAL_STATE = {
    "tasks": [],
    "normalized_events": [],
    "matched_events": [],
    "events_to_update": [],
    "events_to_create": [],
    "unresolved_events": [],
    "decomposed_tasks": [],
    "prioritized_tasks": [],
    "is_valid": False,
    "validation_feedback": "",
    "validation_history": [],
    "refine_target": "",
    "final_output": {},
    "max_iterations": 5,
    "current_iteration": 0,
}


# Cache the compiled pipeline graph so it is only built once per process.
# build_graph() compiles the StateGraph which is expensive — caching avoids
# rebuilding it on every agent call within the same process.
@lru_cache(maxsize=1)
def _get_pipeline():
    return build_graph()


def taskplanner_pipeline(input_text: str) -> Dict:
    """Invoke the deterministic planning pipeline. Returns final_output dict."""
    pipeline = _get_pipeline()
    initial_state = {**PIPELINE_INITIAL_STATE, "raw_input": input_text}
    result = pipeline.invoke(initial_state)
    return result.get("final_output", {})


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentSessionState(TypedDict):
    input_text: str                      # current raw input
    messages: List                       # ChatOpenAI message history for ReAct loop
    plan: Dict[str, Any]                 # latest routing plan from LLM
    pipeline_output: Dict[str, Any]      # final_output from pipeline
    tool_results: List[Dict[str, Any]]   # results from the current execute cycle
    output: str                          # session summary (loaded as history on next run)
    iteration: int                       # ReAct loop counter


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a task management agent. You classify input and decide which tools to call.

Classification rules:
- "task_planning": meeting transcript, SOW, email, or any text containing actionable tasks — classify as task_planning even if this input was previously processed; the pipeline handles deduplication
- "junk": ONLY for gibberish, casual chat with no tasks, or single questions entirely unrelated to work — never classify a SOW, transcript, or document containing deliverables as junk, even on a repeat submission

Tool routing rules:
- For task_planning: always include taskplanner_pipeline first with the full input text
- Add search_tasks after pipeline to verify the tasks were stored correctly
- Add sync_task_to_jira if unresolved_events are likely (complex transcripts with status updates) — only include if you have an actual task_id and task_text to pass
- Add check_owner_availability if input mentions a specific owner and deadline — call it once per owner with a single owner string, NOT a list
- Add generate_report if the user explicitly requests a report
- If observation contains a BLOCKER SIGNAL, call sync_task_to_jira with the task_id and task_text from the signal — the task is blocked and needs escalation
- If observation contains a DEADLINE CHANGE SIGNAL, call check_owner_availability with the owner and new deadline from the signal — verify the owner is available for the updated deadline
- For junk: return empty tool_calls list
- Do NOT use create_task for tasks already created by taskplanner_pipeline

Tool argument constraints:
- check_owner_availability requires: owner (single string, e.g. "Alex"), deadline (optional string)
  WRONG: {{"owner": ["Alex", "Priya"]}}
  RIGHT: one call per owner — {{"owner": "Alex", "deadline": "April 20th"}}
- sync_task_to_jira requires: task_id (UUID string), task_text (string) — never call with empty args
- create_task is only for tasks the pipeline missed — do not re-create tasks already in pipeline_output

Available tools:
  taskplanner_pipeline       — run the AI planning pipeline on the input
  search_tasks               — query active tasks from Postgres
  get_task_by_id             — fetch a single task by UUID
  create_task                — insert a task the pipeline missed (not for pipeline-created tasks)
  update_task_status         — update a field on an existing task
  sync_task_to_jira          — push a task to Jira (requires task_id and task_text)
  check_owner_availability   — check Google Calendar for a single owner (requires owner string)
  generate_report            — produce a task report (markdown, json, or excel)

Respond with ONLY valid JSON — no markdown, no explanation:
{
  "intent": "task_planning",
  "reasoning": "<one sentence>",
  "tool_calls": [
    {"tool": "taskplanner_pipeline", "args": {"input_text": "<full input text here>"}},
    {"tool": "search_tasks", "args": {}}
  ]
}"""


def _build_initial_human_message(input_text: str, history: str) -> str:
    # Combine previous session summary with current input into the first human message.
    # History comes from the Postgres checkpointer — it gives the LLM context
    # about what was processed in earlier runs on the same thread_id.
    return (
        f"Previous session summary (use as context):\n{history or 'No previous sessions.'}"
        f"\n\nCurrent input:\n{input_text}"
    )


def _analyse_pipeline_signals(result: dict) -> List[str]:
    # Extract actionable signals from pipeline output to surface in the observation.
    # Each signal is a plain-English sentence the LLM can act on in the next plan cycle.
    signals = []

    # Surface blocker and deadline_change events so the agent can decide follow-up actions
    event_signals = result.get("event_signals", [])
    blocker_events = [e for e in event_signals if e.get("event_type") == "blocker"]
    deadline_events = [e for e in event_signals if e.get("event_type") == "deadline_change"]

    for e in blocker_events:
        task_id = e.get("matched_task_id", "")
        task_text = e.get("task_text", "")
        signals.append(
            f"BLOCKER SIGNAL: task '{task_text}' (task_id={task_id}) is blocked — "
            "consider syncing to Jira so it can be escalated."
        )

    for e in deadline_events:
        owner = e.get("owner", "")
        deadline = e.get("deadline", "")
        task_text = e.get("task_text", "")
        if owner:
            signals.append(
                f"DEADLINE CHANGE SIGNAL: deadline for '{task_text}' changed to {deadline} (owner={owner}) — "
                "consider checking owner availability."
            )

    unresolved = result.get("unresolved_events", [])
    if unresolved:
        signals.append(
            f"UNRESOLVED EVENTS: {len(unresolved)} update event(s) could not be matched to existing tasks — "
            "consider syncing to Jira for manual review."
        )

    validation = result.get("validation_outcome", {})
    if validation.get("hit_max_iterations"):
        signals.append(
            "VALIDATION WARNING: pipeline hit max iterations without passing — plan quality may be lower than expected."
        )

    return signals


def _build_observe_message(tool_results: List[Dict]) -> str:
    # Format tool results into a human-readable observation that is appended to
    # the message history before the next plan_node call.
    # Truncates long results to 200 chars to avoid bloating the context window.
    lines = ["Tool results from the actions you just took:"]
    for r in tool_results:
        name = r.get("tool", "unknown")
        if "error" in r:
            lines.append(f"- {name}: ERROR — {r['error']}")
        else:
            result = r.get("result", {})
            if isinstance(result, dict):
                # Summarise pipeline output by task count if available
                summary = (
                    f"{result.get('tasks_count', '?')} tasks stored"
                    if "tasks_count" in result
                    else json.dumps(result, default=str)[:200]
                )
                # Surface actionable signals from pipeline output
                if name == "taskplanner_pipeline":
                    for signal in _analyse_pipeline_signals(result):
                        lines.append(f"  ⚠ {signal}")
            else:
                summary = str(result)[:200]
            lines.append(f"- {name}: {summary}")

    # Instruct the LLM to decide what to do next, or return empty tool_calls to end the loop
    lines.append(
        "\nGiven these results, decide your next actions. "
        "If the task is complete, return empty tool_calls []. "
        "Respond with ONLY valid JSON in the same format as before."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP tool execution (async)
# ---------------------------------------------------------------------------

async def _run_mcp_tools(tool_calls: List[Dict]) -> List[Dict]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    # taskplanner_pipeline is executed synchronously in execute_node — skip it here
    mcp_calls = [c for c in tool_calls if c.get("tool") != "taskplanner_pipeline"]
    if not mcp_calls:
        return []

    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
    results = []

    try:
        # Connect to the MCP server via SSE transport.
        # MultiServerMCPClient is NOT used as an async context manager in langchain-mcp-adapters 0.2.2+
        # (async-with support was removed) — instantiate directly and call get_tools() instead.
        client = MultiServerMCPClient({
            "task-planner": {
                "url": f"{mcp_url}/sse",
                "transport": "sse",
            }
        })
        tool_list = await client.get_tools()
        tools = {t.name: t for t in tool_list}

        for call in mcp_calls:
            name = call.get("tool")
            args = call.get("args", {})
            tool_fn = tools.get(name)

            if not tool_fn:
                logger.warning(f"Tool '{name}' not found on MCP server")
                results.append({"tool": name, "error": "not found on MCP server"})
                continue

            try:
                result = await tool_fn.ainvoke(args)
                logger.info(f"MCP tool '{name}' completed")
                results.append({"tool": name, "result": result})
            except Exception as e:
                logger.error(f"MCP tool '{name}' failed: {e}")
                results.append({"tool": name, "error": str(e)})

    except Exception as e:
        logger.error(f"MCP server unreachable at {mcp_url}: {e}")
        results.append({"error": f"MCP server unreachable: {e}"})

    return results


# ---------------------------------------------------------------------------
# Agent nodes
# ---------------------------------------------------------------------------

def plan_node(state: AgentSessionState) -> AgentSessionState:
    # plan_node is the LLM decision point for each ReAct iteration.
    # On iteration 1: builds messages from scratch (system prompt + input + history).
    # On iteration 2+: messages already contain previous AI response + observation from observe_node,
    # so the LLM sees the full conversation history and can make an informed next decision.
    iteration = state.get("iteration", 0) + 1
    logger.info("=" * 60)
    logger.info(f"Agent plan_node: iteration {iteration}")

    messages = state.get("messages", [])

    if not messages:
        # First iteration — seed the conversation with system role + combined input/history message
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_initial_human_message(
                state["input_text"], state.get("output", "")
            )),
        ]

    # temperature=0 for deterministic routing decisions
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    try:
        response = llm.invoke(messages)
        plan = json.loads(response.content)
        # Append the AI response to history so observe_node's message is placed after it
        messages.append(AIMessage(content=response.content))
    except Exception as e:
        logger.error(f"plan_node LLM call failed: {e}")
        # Fallback to junk so the router exits cleanly rather than crashing
        plan = {"intent": "junk", "reasoning": f"LLM error: {e}", "tool_calls": []}
        messages.append(AIMessage(content=json.dumps(plan)))

    logger.info(f"Plan — intent={plan.get('intent')} | tools={[c.get('tool') for c in plan.get('tool_calls', [])]} | {plan.get('reasoning', '')}")

    state["messages"] = messages
    state["plan"] = plan
    state["iteration"] = iteration
    return state


def execute_node(state: AgentSessionState) -> AgentSessionState:
    logger.info("Agent execute_node: executing tool plan")

    plan = state.get("plan", {})
    intent = plan.get("intent", "junk")
    tool_calls = plan.get("tool_calls", [])

    if intent == "junk":
        state["output"] = f"Input not actionable. Reason: {plan.get('reasoning', '')}"
        state["pipeline_output"] = {}
        state["tool_results"] = []
        return state

    pipeline_output = state.get("pipeline_output", {})
    tool_results = []

    # Run taskplanner_pipeline synchronously (always first, only on first iteration)
    pipeline_call = next((c for c in tool_calls if c.get("tool") == "taskplanner_pipeline"), None)
    if pipeline_call:
        input_text = pipeline_call.get("args", {}).get("input_text", state["input_text"])
        logger.info("Calling taskplanner_pipeline")
        pipeline_output = taskplanner_pipeline(input_text)
        tool_results.append({"tool": "taskplanner_pipeline", "result": pipeline_output})
        logger.info(
            f"Pipeline: {pipeline_output.get('tasks_count', 0)} tasks | "
            f"validation passed={pipeline_output.get('validation_outcome', {}).get('passed')} | "
            f"unresolved={len(pipeline_output.get('unresolved_events', []))}"
        )

    # Run MCP tools asynchronously in a fresh event loop with a 60s timeout.
    # asyncio.run() raises RuntimeError if called from a thread that already has a running loop
    # (common under FastAPI). Creating a new loop explicitly avoids that conflict.
    # The wait_for timeout prevents a slow/unreachable MCP server from hanging forever.
    loop = asyncio.new_event_loop()
    try:
        mcp_results = loop.run_until_complete(
            asyncio.wait_for(_run_mcp_tools(tool_calls), timeout=150)
        )
    except asyncio.TimeoutError:
        logger.error("MCP tool execution timed out after 150s")
        mcp_results = [{"error": "MCP tools timed out after 150s"}]
    finally:
        loop.close()
    tool_results.extend(mcp_results)

    state["pipeline_output"] = pipeline_output
    state["tool_results"] = tool_results
    return state


def observe_node(state: AgentSessionState) -> AgentSessionState:
    logger.info(f"Agent observe_node: processing {len(state.get('tool_results', []))} tool result(s)")

    tool_results = state.get("tool_results", [])
    messages = state.get("messages", [])

    if tool_results:
        observation = _build_observe_message(tool_results)
        messages.append(HumanMessage(content=observation))
        logger.info(f"Observation appended to message history (iteration {state.get('iteration', '?')})")

    # Build running session summary from all tool results so far
    all_results = state.get("tool_results", [])
    pipeline_output = state.get("pipeline_output", {})
    state["output"] = _build_summary(pipeline_output, all_results)

    state["messages"] = messages
    # Clear tool_results after converting them to an observation message.
    # This prevents stale results from the current cycle from being re-processed
    # if observe_node is called again in a later iteration.
    state["tool_results"] = []
    return state


def _build_summary(pipeline_output: Dict, tool_results: List[Dict]) -> str:
    tasks_count = pipeline_output.get("tasks_count", 0)
    validation = pipeline_output.get("validation_outcome", {})
    unresolved = pipeline_output.get("unresolved_events", [])

    parts = [f"Processed {tasks_count} task(s), stored to Postgres."]

    if validation.get("hit_max_iterations"):
        parts.append("Warning: validation hit max iterations — plan quality may be lower.")

    if unresolved:
        parts.append(f"{len(unresolved)} unresolved event(s) flagged for review.")

    for r in tool_results:
        tool_name = r.get("tool")
        if tool_name and tool_name != "taskplanner_pipeline":
            detail = r.get("result") or r.get("error", "no result")
            parts.append(f"{tool_name}: {str(detail)[:120]}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def plan_router(state: AgentSessionState) -> str:
    plan = state.get("plan", {})
    intent = plan.get("intent", "junk")
    tool_calls = plan.get("tool_calls", [])
    iteration = state.get("iteration", 0)

    if intent == "junk":
        return "end"
    if not tool_calls:
        logger.info("plan_router: no more tool calls — ending loop")
        return "end"
    if iteration >= MAX_REACT_ITERATIONS:
        logger.info(f"plan_router: hit max ReAct iterations ({MAX_REACT_ITERATIONS}) — ending loop")
        return "end"

    return "execute"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    return (
        f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', 'postgres')}"
        f"@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}"
        f"/{os.getenv('DB_NAME', 'task_planner')}"
    )


def _build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentSessionState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("observe", observe_node)
    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", plan_router, {"execute": "execute", "end": END})
    graph.add_edge("execute", "observe")
    graph.add_edge("observe", "plan")
    return graph


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_agent(input_text: str, thread_id: str = "default") -> Dict:
    from langgraph.checkpoint.postgres import PostgresSaver

    # thread_id scopes the agent's memory — each unique thread_id gets its own
    # independent conversation history stored in the Postgres checkpointer.
    config = {"configurable": {"thread_id": thread_id}}
    db_url = _get_db_url()

    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        # setup() creates the checkpoints table on first run — no-op on subsequent runs
        checkpointer.setup()

        # Load the output field from the most recent checkpoint for this thread.
        # This gives plan_node the context of what was processed in the last session
        # so the LLM can avoid redundant actions across runs.
        previous_output = ""
        checkpoint = checkpointer.get(config)
        if checkpoint:
            previous_output = checkpoint.get("channel_values", {}).get("output", "")
            if previous_output:
                logger.info(f"Loaded previous session summary: {previous_output[:100]}")

        # messages=[] always starts fresh — the Postgres checkpointer persists the full
        # graph state, but we intentionally reset messages each run so the ReAct loop
        # starts clean. Cross-run context is passed through the output/history field instead.
        initial_state: AgentSessionState = {
            "input_text": input_text,
            "messages": [],
            "plan": {},
            "pipeline_output": {},
            "tool_results": [],
            "output": previous_output,
            "iteration": 0,
        }

        agent = _build_agent_graph().compile(checkpointer=checkpointer)
        result = agent.invoke(initial_state, config=config)

    return result
