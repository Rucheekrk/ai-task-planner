# CLAUDE.md — AI Task Planner (LangGraph)

Context file for Claude Code. Read this at the start of every session to get full project context before making any changes.

---

## Project Overview

An AI-powered task management system. A LangGraph ReAct agent sits above a deterministic planning pipeline. The agent receives raw input (meeting transcripts, SOWs), classifies intent, calls the pipeline when appropriate, and routes results to integration tools via a custom MCP server. Built with LangGraph, OpenAI GPT-4o-mini, PostgreSQL + pgvector, and a FastMCP HTTP/SSE server.

**GitHub:** `https://github.com/Rucheekrk/ai-task-planner`  
**Branch:** `main`  
**Run command:** `python3 main.py < datasets/input-2.txt`

---

## Project Structure

```
LangGraph-Task-Agent/
├── main.py                        # Entry point — calls run_agent(); reads from stdin
├── requirements.txt               # Python dependencies
├── docker-compose.yml             # PostgreSQL + pgvector container (port 5432)
│
├── apps/
│   ├── agent.py                   # Top-level ReAct agent — intent classification, tool routing
│   ├── state.py                   # AgentState TypedDict — shared state across pipeline nodes
│   ├── graph.py                   # LangGraph pipeline graph — nodes, edges, routers (no intent node)
│   ├── llm.py                     # OpenAI client — call_llm() and call_llm_json()
│   ├── logger.py                  # Logger factory — per-node log files under logs/
│   │
│   ├── nodes/
│   │   ├── extract.py             # Extract raw task list from input
│   │   ├── normalize.py           # Enrich tasks into structured events (owner, deadline, type)
│   │   ├── match.py               # Match events to existing DB tasks (exact/partial/fuzzy/semantic)
│   │   ├── decompose.py           # Break tasks into actionable subtasks
│   │   ├── prioritize.py          # Assign execution-aware priority (high/medium/low)
│   │   ├── validate.py            # Validate plan quality; detect refinement loops
│   │   ├── refine.py              # Route back to the right node when validation fails
│   │   └── format.py              # Store tasks/events to DB; build final_output
│   │
│   ├── db/
│   │   └── db.py                  # PostgreSQL helpers: insert_task, insert_event,
│   │                              #   update_task_field, update_task_subtasks,
│   │                              #   fetch_active_tasks, fetch_semantic_task_match
│   │
│   └── utils/
│       ├── embeddings.py          # SentenceTransformer (all-MiniLM-L6-v2) → 384-dim vectors
│       └── abbreviations.py      # Static abbreviation expansion map + expand_abbreviations()
│
├── mcp_server/                    # Custom MCP server (HTTP/SSE via FastMCP + uvicorn, port 8001)
│   ├── __init__.py
│   ├── server.py                  # FastMCP app entry point — registers all tools
│   └── tools/
│       ├── __init__.py
│       ├── postgres.py            # search_tasks, get_task_by_id, create_task, update_task_status [full]
│       ├── jira.py                # sync_task_to_jira [stub]
│       ├── calendar.py            # check_owner_availability [stub]
│       └── report.py              # generate_report(format: json|excel|markdown) [stub]
│
├── prompts/
│   ├── extract/prompt.py          # get_extract_prompt(raw_input)
│   ├── normalize/prompt.py        # get_normalize_prompt(raw_input, tasks)
│   ├── decompose/prompt.py        # get_decompose_prompt(tasks)
│   ├── prioritize/prompt.py       # get_prioritize_prompt(tasks)
│   ├── validate/prompt.py         # get_empty_plan_validate_prompt(), get_quality_validate_prompt()
│   └── refine/prompt.py           # get_refine_prompt(validation_feedback, validation_history,
│                                  #   current_iteration, max_iterations)
│
├── datasets/
│   ├── input-1.txt / input-2.txt  # Test inputs (meeting transcripts)
│   ├── expected-output-1.txt / expected-output-2.txt
│   ├── input-sow-1.txt / input-sow-2.txt   # Statement-of-work style inputs
│   └── input-test*.txt            # Targeted test inputs (abbreviations, priority)
│
├── infra/db/schema.sql            # PostgreSQL schema (tasks + task_events tables)
└── logs/                          # Per-node log files (auto-created at runtime)
```

---

## State Schema (`apps/state.py`)

Pipeline-internal state only. The agent has its own state (LangGraph message history + Postgres checkpointer) separate from this.

```python
class AgentState(TypedDict):
    raw_input: str                          # original user input

    tasks: List[Dict]                       # extracted tasks [{task, confidence}]
    normalized_events: List[Dict]           # structured events after normalize node
    matched_events: List[Dict]              # all events with match results attached
    events_to_update: List[Dict]            # matched to existing DB tasks
    events_to_create: List[Dict]            # new tasks (no DB match)
    unresolved_events: List[Dict]           # update events with no DB match found

    decomposed_tasks: List[Dict]            # tasks with subtasks
    prioritized_tasks: List[Dict]           # tasks with priority + subtasks

    is_valid: bool                          # latest validation result
    validation_feedback: str               # latest feedback from validator
    validation_history: List[str]          # feedback from every iteration (loop detection)
    refine_target: str                      # which node to revisit: extract|decompose|prioritize|validate

    final_output: Dict                      # {tasks_count, tasks, unresolved_events, validation_outcome, status}

    max_iterations: int                     # loop limit (default: 5)
    current_iteration: int                  # incremented each time validate node runs
```

---

## Graph Flow (`apps/graph.py`)

Intent classification is handled by the agent before the pipeline is called — not inside the pipeline.

```
extract → normalize → match → decompose → prioritize → validate
                                                            │
                                               is_valid or max_iterations
                                                    ↓              ↓
                                                  final          refine
                                                                   │
                                          refine_target: extract | decompose
                                                        | prioritize | validate
```

**Routers:**
- `validate_router`: `is_valid=True` or `current_iteration >= max_iterations` → `final`, else → `refine`
- `refine_router`: reads `refine_target` from state → routes back to the appropriate node

---

## Database (`infra/db/schema.sql`)

**`tasks` table** — current state of each task:
- `task_id` (UUID PK), `task_text`, `normalized_task_text`, `owner`, `status`, `deadline`, `blocker`, `priority`, `subtasks` (TEXT[]), `is_active` (BOOL), `task_embedding` (vector via pgvector), `created_at`, `updated_at`

**`task_events` table** — immutable event log:
- `event_id` (UUID PK), `task_id` (FK), `event_type`, `task_text`, `owner`, `status`, `deadline`, `blocker`, `dependency`, `match_method`, `match_confidence`, `source_input`, `created_at`

**pgvector** is used for semantic similarity search. The `task_embedding` column stores 384-dim vectors from `all-MiniLM-L6-v2`. Run via Docker: `docker-compose up -d`

---

## Matching Logic (`apps/nodes/match.py`)

Four-step cascade per event:
1. **Exact** — normalized text equality → `high` confidence
2. **Partial** — substring containment (update events only) → `high` confidence
3. **Fuzzy** — `SequenceMatcher` ratio. New tasks: threshold ≥ 0.75. Update events: ≥ 0.50
4. **Semantic** — pgvector cosine similarity. Threshold ≥ 0.60. Score ≥ 0.85 = high, ≥ 0.70 = medium

`force_match=True` for all non-`new_task` event types (they must match an existing task). Unmatched update events → `unresolved_events`.

---

## Validation + Refinement Loop

### How it works
- `validate.py` runs after `prioritize`. It increments `current_iteration` each call.
- Two validation prompts: `get_empty_plan_validate_prompt` (no tasks) and `get_quality_validate_prompt` (plan quality).
- **Loop detection:** if `validation_feedback` equals `validation_history[-1]`, the refine cycle ran but produced no change → forces `is_valid = True` to break out.
- Feedback is always appended to `validation_history` regardless of outcome.

### Refine routing (`refine.py` + `prompts/refine/prompt.py`)
The LLM decides which node to revisit based on feedback:
- `extract` — missing or incorrect tasks
- `decompose` — weak subtasks
- `prioritize` — wrong priority/dependency order
- `validate` — plan is acceptable or empty plan is valid

**Iteration-aware rules in the prompt:**
- If feedback hasn't changed since last iteration → pick a different target or accept
- If on the last iteration (`current_iteration == max_iterations`) → route to `validate` (accept)

---

## LLM + Config

- **Model:** `gpt-4o-mini` via OpenAI API (`apps/llm.py`)
- **Client:** `openai.OpenAI` using `client.responses.create()`
- **API key:** set via `.env` as `OPENAI_API_KEY`
- All pipeline LLM calls return parsed JSON
- Agent makes one structured LLM call (intent classification + tool routing plan); full ReAct loop deferred

**LLM call budget per run:**

| Call | Where | Purpose |
|------|-------|---------|
| 1 | Agent (`apps/agent.py`) | Intent classification + tool routing plan (replaces the old intent node call — net total unchanged) |
| N | Pipeline nodes | extract, normalize, decompose, prioritize, validate, refine (conditional) |

Both are calls to the same GPT-4o-mini model. The difference is what the output controls:
- **Pipeline calls** transform content (extract tasks, normalize fields, decompose). The graph execution path is fixed regardless of what the LLM returns — extract always precedes normalize, normalize always precedes match. LLM output fills slots in a fixed structure.
- **Agent call** produces a routing decision. Its output determines what runs next — call the pipeline or return early, call Jira or skip. Execution path changes based on LLM output.

---

## Environment Setup

```bash
# 1. Activate venv
source venv/bin/activate

# 2. Start PostgreSQL + pgvector
docker-compose up -d

# 3. Start MCP server (separate terminal)
python3 -m mcp_server.server

# 4. Run agent
python3 main.py < datasets/input-2.txt
python3 main.py < datasets/input-sow-1.txt
```

`.env` required fields:
```
OPENAI_API_KEY=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=task_planner
DB_USER=postgres
DB_PASSWORD=postgres
MCP_SERVER_URL=http://localhost:8001
```

---

## Agent Architecture (`apps/agent.py`)

The agent is the system entry point. It sits above the pipeline and owns all external integration decisions.

```
stdin input
    ↓
Agent (apps/agent.py)
    ├── Reads conversation history from Postgres checkpointer (thread_id scoped)
    │
    ├── LLM Call #1 — Intent + Tool Routing Plan
    │       Input:  raw text + history
    │       Output: { intent: "task_planning"|"junk", tool_calls: [{tool, args}, ...] }
    │
    ├── if intent = "junk" → return early, no pipeline call
    │
    └── if intent = "task_planning":
            Execute tool_calls in order:
            1. taskplanner_pipeline(input_text)          ← always first for task inputs
            2. search_tasks / get_task_by_id             ← verify Postgres storage
            3. sync_task_to_jira(task_id, ...)           ← conditional on plan (stub)
            4. check_owner_availability(owner, deadline) ← conditional on plan (stub)
            5. generate_report(format)                   ← conditional on plan (stub)
```

**Agent memory:** Postgres checkpointer (`langgraph-checkpoint-postgres`), keyed by `thread_id`. Persists across process runs — agent accumulates context over multiple sessions.

**Tool: `taskplanner_pipeline(input_text: str)`**
- Wraps `build_graph().invoke(...)` synchronously
- Pipeline entry point: `extract` (no intent node)
- Returns: `{ tasks_count, tasks, unresolved_events, validation_outcome, status }`
- Agent uses `unresolved_events` to decide if Jira escalation is needed
- Agent uses `validation_outcome` to flag plans that hit max iterations without passing

**MCP Server (`mcp_server/`)** — HTTP/SSE, port 8001
- Runs independently via `python3 -m mcp_server.server`
- Agent connects via `langchain-mcp-adapters` SSE client using `MCP_SERVER_URL`
- Tools: `search_tasks`, `get_task_by_id`, `create_task`, `update_task_status` [Postgres, full], `sync_task_to_jira` [stub], `check_owner_availability` [stub], `generate_report` [stub]

**State ownership:**

| Layer | State | Persisted in |
|-------|-------|-------------|
| Agent | Intent decision, tool routing plan, tool results | Postgres checkpointer |
| Pipeline | Extracted tasks, matched events, validation | In-process AgentState only |
| MCP tools | Live task/event records | Postgres tasks/task_events tables |

**Extensibility:** Agent currently makes 1 LLM call (plan-then-execute). Full ReAct loop (think → call → observe → think again) is the next step — just lift the iteration cap.

---

## Recently Completed Work

| Commit | What was done |
|--------|--------------|
| `c3d727e` | **Validation loop detection** — added `validation_history: List[str]` to state; validate node detects repeated feedback and forces `is_valid=True`; refine prompt gets `current_iteration`, `max_iterations`, `validation_history` for iteration-aware routing |
| `2651c49` | **Abbreviation expansion + validator fix** — static `ABBREVIATION_MAP` utility with LLM fallback; fixed validator incorrectly flagging final-step tasks as priority errors; added prerequisite vs dependent priority rules to validate prompt |
| `dd639f4` | **DB persistence fix** — persist priority and subtasks fields to DB; fixed pipeline and prompt bugs |
| `c1e825a` | **Prompt modularization** — moved all prompts to `prompts/` directory with separate modules per node |
| `7b972b6` | **Semantic matching** — added pgvector cosine similarity as Step 4 of matching; improved partial/fuzzy thresholds; added unresolved event routing |

---

## Known Behaviors / Edge Cases

- `analytics module` task (from `input-2.txt`) is explicitly excluded by the extract prompt since Rahul said "no action item for now" — this is intentional.
- `current_iteration` starts at `0` in `main.py` and is incremented at the top of `validate.py`, so the first validation run always shows `current_iteration: 1`.
- The `pgvector` `embeddings.position_ids` warning at startup is harmless (known model load artifact from `sentence-transformers`).
- `match.py` uses `unresolved` as `match_method` for update events with no DB match — check `unresolved_events` in state for these.
- `format.py` writes `source_input` (full transcript) into every `task_events` row — this is intentional for auditability but makes JSON output large.

---

## Potential Next Steps

1. **Agent + MCP server implementation** — implement `apps/agent.py`, `mcp_server/`, remove intent node, update `main.py` (in progress — architecture finalized 2026-04-18)
2. **Full ReAct loop for agent** — currently one LLM call (plan-then-execute); extend to think→call→observe→think loop when integration tools return real data
3. **Jira integration** — replace `sync_task_to_jira` stub with real Jira REST API calls (requires `JIRA_URL`, `JIRA_TOKEN`, `JIRA_PROJECT` env vars)
4. **Calendar integration** — replace `check_owner_availability` stub with Google Calendar or Outlook API
5. **Report generation** — implement `generate_report(format)` for json/excel/markdown output
6. **FastAPI frontend** — expose agent as HTTP endpoint; MCP server already on HTTP/SSE so transport is compatible
7. **Validation prompt tuning** — the quality validate prompt may still be too strict on some edge cases; `input-test-priority.txt` exists for targeted testing
8. ~~**Multi-run deduplication**~~ — ✅ Done: `fetch_task_by_normalized_text()` guard in `store_tasks` prevents duplicate inserts across runs

---

## Future Enhancements (deferred — not core goals)

- **Relative deadline resolution** — deadlines like "tomorrow EOD" or "next Tuesday" are stored as strings; converting them to absolute ISO dates (`YYYY-MM-DD`) at normalize time would make them queryable and sortable. `python-dateutil` is already in requirements. Approach: post-process the `deadline` field in `normalize.py` after LLM output using a `resolve_deadline(text, today)` utility that handles common patterns (today, tomorrow, next \<weekday\>, EOW, EOM) with a `dateutil.parser` fuzzy-parse fallback.
