import time

import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Task Planner",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.pipeline-node {
    display: inline-block;
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 0.82em;
    font-weight: 600;
    margin: 2px;
}
.node-done    { background: #d1fae5; color: #065f46; }
.node-pending { background: #f3f4f6; color: #9ca3af; }

.signal-box {
    border-left: 4px solid #f97316;
    background: #fff7ed;
    padding: 8px 12px;
    border-radius: 4px;
    margin: 5px 0;
    font-size: 0.9em;
}
.badge {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 700;
    margin-right: 4px;
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

PRIORITY_COLORS = {"high": "#ef4444", "medium": "#f59e0b", "low": "#10b981"}
STATUS_COLORS   = {
    "not_started": "#6b7280",
    "in_progress":  "#3b82f6",
    "completed":    "#10b981",
    "blocked":      "#ef4444",
}


def badge(label: str, color: str) -> str:
    return (
        f'<span class="badge" style="background:{color}22;color:{color}">'
        f"{label}</span>"
    )


def api_health() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=2).status_code == 200
    except Exception:
        return False


def submit_run(text: str, thread_id: str, force_run: bool = False) -> tuple:
    r = requests.post(
        f"{API_BASE}/run",
        json={"input_text": text, "thread_id": thread_id, "force_run": force_run},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return data["job_id"], data.get("from_cache", False)


def poll_job(job_id: str) -> dict:
    r = requests.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_projects() -> list:
    try:
        r = requests.get(f"{API_BASE}/projects", timeout=5)
        r.raise_for_status()
        return r.json().get("projects", [])
    except Exception:
        return []


def fetch_tasks(query=None, owner=None, status=None, project_id=None) -> list:
    params = {k: v for k, v in {"query": query, "owner": owner, "status": status, "project_id": project_id}.items() if v}
    r = requests.get(f"{API_BASE}/tasks", params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("tasks", [])


def patch_task(task_id: str, field: str, value: str) -> dict:
    r = requests.patch(
        f"{API_BASE}/tasks/{task_id}",
        json={"field": field, "value": value},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📋 AI Task Planner")
    alive = api_health()
    st.markdown(f"**API:** {'🟢 Online' if alive else '🔴 Offline'}")
    st.divider()

    existing_projects = fetch_projects() if alive else []
    NEW_PROJECT = "＋ New project…"
    project_options = [NEW_PROJECT] + existing_projects

    selected = st.selectbox(
        "Project",
        project_options,
        help="Each project has its own task scope and agent memory.",
    )

    if selected == NEW_PROJECT:
        new_name = st.text_input("Project name", placeholder="e.g. alpha-corp-sow")
        thread_id = new_name.strip() if new_name.strip() else "default"
        if not new_name.strip():
            st.caption("Enter a project name to begin.")
        else:
            st.caption(f"New project: **{thread_id}**")
    else:
        thread_id = selected
        st.caption(f"Project: **{thread_id}**")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_run, tab_board, tab_tracker = st.tabs(["🚀 Process Input", "📋 Task Board", "📊 Task Tracker"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Process Input
# ─────────────────────────────────────────────────────────────────────────────

with tab_run:
    col_in, col_out = st.columns([2, 3], gap="large")

    # ── Input panel ───────────────────────────────────────────────────────────
    with col_in:
        st.subheader("Input")
        mode = st.radio("Source", ["Paste text", "Upload .txt"], horizontal=True, label_visibility="collapsed")

        input_text = ""
        if mode == "Paste text":
            input_text = st.text_area(
                "input",
                height=320,
                placeholder="Paste a meeting transcript, SOW, or any task-related text…",
                label_visibility="collapsed",
            )
        else:
            uploaded = st.file_uploader("Upload", type=["txt"], label_visibility="collapsed")
            if uploaded:
                input_text = uploaded.read().decode("utf-8")
                st.success(f"Loaded {uploaded.name} ({len(input_text):,} chars)")
                with st.expander("Preview"):
                    st.text(input_text[:600] + ("…" if len(input_text) > 600 else ""))

        is_running = "active_job_id" in st.session_state

        if not alive:
            st.warning("API is offline — start the FastAPI server on port 8000 first.")

        if is_running:
            st.button("⏳ Running…", type="primary", disabled=True,
                      use_container_width=True, key="run_btn_running")
        else:
            can_run = alive and bool(input_text.strip())
            btn_col, force_col = st.columns([3, 2])

            with btn_col:
                run_btn = st.button("▶ Run Agent", type="primary",
                                    disabled=not can_run,
                                    use_container_width=True, key="run_btn")
            with force_col:
                force_btn = st.button("🔄 Force Re-run",
                                      disabled=not can_run,
                                      use_container_width=True, key="force_btn",
                                      help="Bypass cache and re-run the pipeline even if this document was processed before.")

            for pressed, force in [(run_btn, False), (force_btn, True)]:
                if pressed and input_text.strip():
                    try:
                        job_id, from_cache = submit_run(input_text, thread_id, force_run=force)
                        st.session_state["active_job_id"] = job_id
                        st.session_state["job_start"] = time.time()
                        st.session_state["from_cache"] = from_cache
                        st.session_state.pop("last_result", None)
                        st.session_state.pop("last_from_cache", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to start run: {e}")
                    break

    # ── Results panel ─────────────────────────────────────────────────────────
    with col_out:
        st.subheader("Results")

        if is_running:
            elapsed = int(time.time() - st.session_state.get("job_start", time.time()))
            st.info(f"Agent is thinking… {elapsed}s elapsed")

            try:
                job = poll_job(st.session_state["active_job_id"])
            except Exception as e:
                st.error(f"Polling error: {e}")
                del st.session_state["active_job_id"]
                st.session_state.pop("job_start", None)
                job = None

            if job:
                if job["status"] == "completed":
                    result = job["result"]
                    st.session_state["last_result"] = result
                    st.session_state["last_from_cache"] = job.get("from_cache", False)
                    st.session_state["run_index"] = st.session_state.get("run_index", 0) + 1
                    st.session_state["tasks_dirty"] = True
                    del st.session_state["active_job_id"]
                    st.session_state.pop("job_start", None)
                    st.session_state.pop("from_cache", None)
                    st.rerun()
                elif job["status"] == "failed":
                    st.error(f"Agent failed: {job.get('error', 'unknown error')}")
                    del st.session_state["active_job_id"]
                    st.session_state.pop("job_start", None)
                else:
                    time.sleep(2)
                    st.rerun()

        else:
            result = st.session_state.get("last_result")

            if not result:
                st.info("Run the agent to see results here.")
            else:
                if st.session_state.get("last_from_cache"):
                    st.info("⚡ Retrieved from cache — this document was processed before. Use **Force Re-run** to re-run the pipeline.")

                # ── Intent + summary ──────────────────────────────────────────
                intent = result.get("intent", "unknown")
                n_tasks = result.get("tasks_count", 0)
                output  = result.get("output", "")

                if intent == "junk":
                    st.warning("Agent classified this input as non-actionable. No pipeline was run.")
                    if output:
                        st.info(output)
                else:
                    c1, c2 = st.columns(2)
                    c1.metric("Intent", intent.replace("_", " ").title())
                    c2.metric("Tasks processed", n_tasks)
                    if output:
                        st.info(output)

                # ── Pipeline stages ───────────────────────────────────────────
                st.markdown("---")
                st.markdown("**Pipeline stages**")

                vo          = result.get("validation_outcome", {})
                tasks       = result.get("tasks", [])
                n_subtasks  = sum(len(t.get("subtasks", [])) for t in tasks)
                p_counts    = {"high": 0, "medium": 0, "low": 0}
                for t in tasks:
                    p_counts[t.get("priority", "medium")] += 1

                passed   = vo.get("passed", False)
                iters    = vo.get("iterations", 1)
                hit_max  = vo.get("hit_max_iterations", False)

                stages = [
                    ("Extract",    f"{n_tasks} task(s) found"),
                    ("Normalize",  "events structured"),
                    ("Match",      f"{len(result.get('event_signals', []))} signal(s), {len(result.get('unresolved_events', []))} unresolved"),
                    ("Decompose",  f"{n_subtasks} subtask(s) generated"),
                    ("Prioritize", f"🔴 {p_counts['high']}  🟡 {p_counts['medium']}  🟢 {p_counts['low']}"),
                    ("Validate",   f"{'✅ Passed' if passed else '⚠️ Max iters' if hit_max else '❌ Failed'} (iter {iters})"),
                ]

                run_index = st.session_state.get("run_index", 0)
                animated_key = f"pipeline_animated_{run_index}"

                pipeline_slot = st.empty()

                def render_pipeline(n_done: int) -> str:
                    html = '<div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:6px 0">'
                    for i, (name, tip) in enumerate(stages):
                        css  = "node-done" if i < n_done else "node-pending"
                        icon = "✓" if i < n_done else "○"
                        html += f'<span class="pipeline-node {css}" title="{tip}">{icon} {name}</span>'
                        if i < len(stages) - 1:
                            html += '<span style="color:#d1d5db;margin:0 2px">→</span>'
                    html += "</div>"
                    return html

                if not st.session_state.get(animated_key):
                    for i in range(len(stages) + 1):
                        pipeline_slot.markdown(render_pipeline(i), unsafe_allow_html=True)
                        time.sleep(0.18)
                    st.session_state[animated_key] = True
                else:
                    pipeline_slot.markdown(render_pipeline(len(stages)), unsafe_allow_html=True)

                with st.expander("Stage details"):
                    for name, detail in stages:
                        st.markdown(f"**{name}** — {detail}")

                if not passed:
                    feedback = vo.get("final_feedback", "")
                    if feedback:
                        st.warning(f"Validation feedback: {feedback}")

                # ── Tasks from this run ───────────────────────────────────────
                if tasks:
                    st.markdown("---")
                    st.markdown("**Tasks from this run**")
                    for t in tasks:
                        pri   = t.get("priority", "medium")
                        color = PRIORITY_COLORS.get(pri, "#6b7280")
                        label = pri.upper()
                        with st.expander(t.get("task", "")[:80]):
                            st.markdown(badge(label, color), unsafe_allow_html=True)
                            subs = t.get("subtasks", [])
                            if subs:
                                for s in subs:
                                    st.markdown(f"- {s}")

                # ── Agent observations ────────────────────────────────────────
                event_signals = result.get("event_signals", [])
                unresolved    = result.get("unresolved_events", [])

                if event_signals or unresolved:
                    st.markdown("---")
                    st.markdown("**Agent observations**")

                    signal_counts: dict = {}
                    for s in event_signals:
                        et = s.get("event_type", "unknown")
                        signal_counts[et] = signal_counts.get(et, 0) + 1

                    icons = {"blocker": "🚫", "deadline_change": "📅", "status_change": "🔄", "owner_change": "👤"}
                    for et, count in signal_counts.items():
                        icon = icons.get(et, "📌")
                        label = et.replace("_", " ").title()
                        st.markdown(
                            f'<div class="signal-box">{icon} <strong>{label}</strong>: {count} event(s) detected</div>',
                            unsafe_allow_html=True,
                        )

                    if unresolved:
                        st.markdown(
                            f'<div class="signal-box">⚠️ <strong>Unresolved events</strong>: '
                            f'{len(unresolved)} update(s) could not be matched to existing tasks</div>',
                            unsafe_allow_html=True,
                        )
                        with st.expander(f"View {len(unresolved)} unresolved event(s)"):
                            for u in unresolved:
                                st.json(u)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Task Board
# ─────────────────────────────────────────────────────────────────────────────

with tab_board:
    hdr, refresh_btn_col = st.columns([5, 1])
    hdr.subheader("Task Board")
    hdr.caption("All active tasks in the database — includes tasks from all previous runs.")
    if refresh_btn_col.button("🔄 Refresh", key="board_refresh"):
        st.session_state.pop("board_tasks", None)

    if st.session_state.get("tasks_dirty") or "board_tasks" not in st.session_state:
        try:
            st.session_state["board_tasks"] = fetch_tasks()
            st.session_state["tasks_dirty"] = False
        except Exception as e:
            st.error(f"Could not load tasks: {e}")
            st.session_state["board_tasks"] = []

    all_tasks = st.session_state.get("board_tasks", [])

    high_tasks   = [t for t in all_tasks if t.get("priority") == "high"]
    medium_tasks = [t for t in all_tasks if t.get("priority") == "medium"]
    low_tasks    = [t for t in all_tasks if t.get("priority") == "low"]

    def task_cards(tasks: list):
        if not tasks:
            st.caption("None")
            return
        for task in tasks:
            text     = task.get("task_text", "")
            owner    = task.get("owner") or "—"
            deadline = task.get("deadline") or "—"
            status   = task.get("status", "not_started")
            subtasks = task.get("subtasks") or []
            priority = task.get("priority", "medium")

            sc = STATUS_COLORS.get(status, "#6b7280")
            pc = PRIORITY_COLORS.get(priority, "#6b7280")

            with st.expander(f"{text[:65]}{'…' if len(text) > 65 else ''}"):
                st.markdown(
                    badge(status.replace("_", " ").title(), sc) +
                    badge(priority.upper(), pc),
                    unsafe_allow_html=True,
                )
                st.markdown(f"👤 **{owner}** &nbsp; 📅 **{deadline}**", unsafe_allow_html=True)
                if subtasks:
                    st.markdown("**Subtasks**")
                    for s in subtasks:
                        st.markdown(f"- {s}")

    col_h, col_m, col_l = st.columns(3)

    with col_h:
        st.markdown(f"### 🔴 High `{len(high_tasks)}`")
        task_cards(high_tasks)

    with col_m:
        st.markdown(f"### 🟡 Medium `{len(medium_tasks)}`")
        task_cards(medium_tasks)

    with col_l:
        st.markdown(f"### 🟢 Low `{len(low_tasks)}`")
        task_cards(low_tasks)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Task Tracker
# ─────────────────────────────────────────────────────────────────────────────

with tab_tracker:
    st.subheader("Task Tracker")

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    search_q      = fc1.text_input("Search tasks", placeholder="Search…", label_visibility="collapsed")
    filter_owner  = fc2.text_input("Owner", placeholder="Filter by owner", label_visibility="collapsed")
    filter_status = fc3.selectbox(
        "Status",
        ["All", "not_started", "in_progress", "completed", "blocked"],
        label_visibility="collapsed",
    )

    try:
        tracker_tasks = fetch_tasks(
            query=search_q or None,
            owner=filter_owner or None,
            status=None if filter_status == "All" else filter_status,
        )
    except Exception as e:
        st.error(f"Could not load tasks: {e}")
        tracker_tasks = []

    # ── Task table ────────────────────────────────────────────────────────────
    if tracker_tasks:
        rows = []
        for t in tracker_tasks:
            rows.append({
                "Task":     t.get("task_text", "")[:80],
                "Owner":    t.get("owner") or "—",
                "Deadline": t.get("deadline") or "—",
                "Priority": t.get("priority", "—").upper(),
                "Status":   t.get("status", "—").replace("_", " ").title(),
                "Updated":  str(t.get("updated_at", ""))[:16],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(tracker_tasks)} task(s)")
    else:
        st.info("No tasks found. Run the agent first or adjust filters.")

    # ── Inline update form ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Update a task**")

    if tracker_tasks:
        task_options = {
            f"{t.get('task_text', '')[:55]}… ({str(t.get('task_id',''))[:8]})": t.get("task_id", "")
            for t in tracker_tasks
        }
        selected_label = st.selectbox("Task", list(task_options.keys()), label_visibility="collapsed")
        selected_id    = task_options[selected_label]

        uf1, uf2, uf3 = st.columns([2, 2, 1])
        update_field   = uf1.selectbox("Field", ["status", "priority", "owner", "deadline", "blocker"], label_visibility="collapsed")

        if update_field == "status":
            update_value = uf2.selectbox("Value", ["not_started", "in_progress", "completed", "blocked"], label_visibility="collapsed")
        elif update_field == "priority":
            update_value = uf2.selectbox("Value", ["high", "medium", "low"], label_visibility="collapsed")
        else:
            update_value = uf2.text_input("Value", label_visibility="collapsed")

        uf3.markdown("<br>", unsafe_allow_html=True)
        if uf3.button("Update", type="primary"):
            if selected_id and update_value:
                try:
                    patch_task(selected_id, update_field, update_value)
                    st.success(f"Updated `{update_field}` → `{update_value}`")
                    st.session_state["tasks_dirty"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")
    else:
        st.caption("Load tasks first.")
