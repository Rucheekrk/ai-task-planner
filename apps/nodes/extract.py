from difflib import SequenceMatcher
import re

from apps.llm import call_llm_json
from apps.logger import get_logger
from apps.state import AgentState
from prompts.extract.prompt import get_extract_prompt

logger = get_logger("EXTRACT")

# Inputs shorter than this are sent as a single LLM call — no chunking needed.
# ~6000 chars ≈ 1500 words, well within gpt-4o-mini's context with the extract prompt.
CHUNK_THRESHOLD = 6000
CHUNK_SIZE = 6000
# Overlap ensures a task that straddles two chunk boundaries appears fully in one of them.
CHUNK_OVERLAP = 200


def _chunk_text(text: str) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        if end < len(text):
            # Prefer breaking at a sentence boundary within the last 200 chars of the window
            # so tasks are not split mid-sentence across chunks.
            boundary = text.rfind('.', end - 200, end)
            if boundary == -1:
                boundary = text.rfind('\n', end - 200, end)
            if boundary != -1:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end - CHUNK_OVERLAP
    return [c for c in chunks if c]


def _dedup_tasks(task_lists: list) -> list:
    # Merge task lists extracted from multiple chunks, dropping near-duplicates.
    # The same task can appear in two consecutive chunks due to the overlap window —
    # exact normalized match catches identical phrasing, fuzzy match (>0.85) catches
    # minor wording differences from the same underlying task.
    def normalize(t):
        return re.sub(r"[^\w\s]", "", t.lower().strip())

    merged, seen = [], []
    for tasks in task_lists:
        for item in tasks:
            norm = normalize(item.get("task", ""))
            if norm in seen:
                continue
            if any(SequenceMatcher(None, norm, s).ratio() > 0.85 for s in seen):
                continue
            merged.append(item)
            seen.append(norm)
    return merged


def task_extract_node(state: AgentState) -> AgentState:
    logger.info("=" * 60)
    logger.info("Running Task Extract Node")

    raw_input = state.get("raw_input", "")

    # Short inputs go through as a single LLM call — chunking only kicks in for long docs.
    if len(raw_input) <= CHUNK_THRESHOLD:
        chunks = [raw_input]
    else:
        chunks = _chunk_text(raw_input)
        logger.info(f"Input ({len(raw_input)} chars) split into {len(chunks)} chunk(s)")

    all_task_lists = []

    for i, chunk in enumerate(chunks):
        prompt = get_extract_prompt(raw_input=chunk)
        try:
            result = call_llm_json(prompt)
        except Exception as e:
            logger.error(f"LLM call failed on chunk {i + 1}/{len(chunks)}: {e}")
            continue

        tasks = result.get("tasks", [])
        if not isinstance(tasks, list):
            logger.warning(f"Chunk {i + 1}: invalid tasks format from LLM, skipping")
            continue

        cleaned = []
        valid_confidence = {"high", "medium", "low"}
        for item in tasks:
            if isinstance(item, dict) and "task" in item:
                task_text = item["task"].strip()
                confidence = item.get("confidence", "medium")
                confidence = confidence.lower() if isinstance(confidence, str) else "medium"
                if confidence not in valid_confidence:
                    confidence = "medium"
                cleaned.append({"task": task_text, "confidence": confidence})

        if cleaned:
            logger.info(f"Chunk {i + 1}/{len(chunks)}: {len(cleaned)} task(s) extracted")
            all_task_lists.append(cleaned)

    final_tasks = _dedup_tasks(all_task_lists)
    state["tasks"] = final_tasks
    logger.info(f"Extracted {len(final_tasks)} tasks total across {len(chunks)} chunk(s)")

    return state
