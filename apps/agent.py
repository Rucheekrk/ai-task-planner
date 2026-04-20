import asyncio
import json
import os
from functools import lru_cache
from typing import Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from apps.graph import build_graph
from apps.llm import call_llm_json
from apps.logger import get_logger

load_dotenv()
logger = get_logger("AGENT")


# ---------------------------------------------------------------------------
# Pipeline wrapper
# ---------------------------------------------------------------------------

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
# Agent state — separate from pipeline AgentState
# ---------------------------------------------------------------------------

class AgentSessionState(TypedDict):
    input_text: str                     # current raw input
    plan: Dict[str, Any]               # routing plan from LLM call
    pipeline_output: Dict[str, Any]    # final_output from pipeline
    tool_results: List[Dict[str, Any]] # results from all tool calls
    output: str                         # session summary (also used as history for next run)


# ---------------------------------------------------------------------------
# Routing prompt
# ---------------------------------------------------------------------------

_ROUTING_PROMPT = """You are a task management agent. Analyze the input and return a JSON routing plan.

Previous session summary (use as context for routing decisions):
{history}

Current input:
{input_text}

Classification rules:
- "task_planning": meeting transcript, SOW, email, or any text containing actionable tasks
- "junk": casual chat, single questions, gibberish, or text with no tasks to extract

Tool routing rules:
- For task_planning: always include taskplanner_pipeline first with the full input text
- Add search_tasks after pipeline to verify the tasks were stored correctly
- Add sync_task_to_jira if unresolved_events are likely (complex transcripts with status updates)
- Add check_owner_availability if input mentions owners and deadlines
- For junk: return empty tool_calls list

Available tools:
  taskplanner_pipeline  — run the AI planning pipeline on the input
  search_tasks          — query active tasks from Postgres
  get_task_by_id        — fetch a single task by UUID
  create_task           — insert a task the pipeline missed
  update_task_status    — update a field on an existing task
  sync_task_to_jira     — push tasks to Jira (stub)
  check_owner_availability — check calendar for owner (stub)
  generate_report       — produce a task report (stub)

Respond with ONLY valid JSON — no markdown, no explanation:
{{
  "intent": "task_planning",
  "reasoning": "<one sentence>",
  "tool_calls": [
    {{"tool": "taskplanner_pipeline", "args": {{"input_text": "<full input text here>"}}}},
    {{"tool": "search_tasks", "args": {{}}}}
  ]
}}"""


def _build_routing_prompt(input_text: str, history: str) -> str:
    return _ROUTING_PROMPT.format(
        input_text=input_text,
        history=history if history else "No previous sessions.",
    )


# ---------------------------------------------------------------------------
# MCP tool execution (async — runs in its own event loop)
# ---------------------------------------------------------------------------

async def _run_mcp_tools(tool_calls: List[Dict]) -> List[Dict]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    mcp_calls = [c for c in tool_calls if c.get("tool") != "taskplanner_pipeline"]
    if not mcp_calls:
        return []

    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
    results = []

    try:
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
    logger.info("=" * 60)
    logger.info("Agent plan_node: making routing LLM call")

    # state["output"] carries the previous session summary loaded by run_agent()
    prompt = _build_routing_prompt(state["input_text"], state.get("output", ""))

    try:
        plan = call_llm_json(prompt)
    except Exception as e:
        logger.error(f"Routing LLM call failed: {e}")
        plan = {"intent": "junk", "reasoning": f"LLM error: {e}", "tool_calls": []}

    logger.info(f"Plan — intent={plan.get('intent')} | {plan.get('reasoning', '')}")
    state["plan"] = plan
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

    pipeline_output = {}
    tool_results = []

    # Run taskplanner_pipeline synchronously (always first)
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

    # Run MCP tools asynchronously
    mcp_results = asyncio.run(_run_mcp_tools(tool_calls))
    tool_results.extend(mcp_results)

    state["pipeline_output"] = pipeline_output
    state["tool_results"] = tool_results
    state["output"] = _build_summary(pipeline_output, tool_results)

    logger.info(f"Session summary: {state['output']}")
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
    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", END)
    return graph


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_agent(input_text: str, thread_id: str = "default") -> Dict:
    from langgraph.checkpoint.postgres import PostgresSaver

    config = {"configurable": {"thread_id": thread_id}}
    db_url = _get_db_url()

    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        checkpointer.setup()  # creates checkpoints table on first run — no-op after that

        # Load previous session summary to use as history context in plan_node
        previous_output = ""
        checkpoint = checkpointer.get(config)
        if checkpoint:
            previous_output = checkpoint.get("channel_values", {}).get("output", "")
            if previous_output:
                logger.info(f"Loaded previous session summary: {previous_output[:100]}")

        initial_state: AgentSessionState = {
            "input_text": input_text,
            "plan": {},
            "pipeline_output": {},
            "tool_results": [],
            "output": previous_output,  # plan_node reads this as history
        }

        agent = _build_agent_graph().compile(checkpointer=checkpointer)
        result = agent.invoke(initial_state, config=config)

    return result
