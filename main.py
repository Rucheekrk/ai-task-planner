import argparse
import sys
import json

from dotenv import load_dotenv

from apps.agent import run_agent
from apps.logger import get_logger

# Load environment variables from .env (OPENAI_API_KEY, DB_*, MCP_SERVER_URL)
load_dotenv()
logger = get_logger("MAIN")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Task Planner CLI")
    parser.add_argument(
        "--thread-id",
        default="default",
        help="Project / thread ID — scopes agent memory and task matching to this project (default: 'default')",
    )
    args = parser.parse_args()
    thread_id = args.thread_id

    print(f"Project: {thread_id}")
    print("Reading input from stdin... (use: python3 main.py --thread-id <project> < input.txt)\n")

    user_input = sys.stdin.read().strip()

    result = run_agent(user_input, thread_id=thread_id)

    # Log high-level outcome for monitoring
    logger.info(f"Intent: {result.get('plan', {}).get('intent')}")
    logger.info(f"Tasks processed: {result.get('pipeline_output', {}).get('tasks_count', 0)}")
    logger.info(f"Tool calls made: {len(result.get('tool_results', []))}")
    logger.info(f"Session summary: {result.get('output', '')}")

    print()
    print("=== JSON_OUTPUT_BEGIN ===")
    print(json.dumps(result, indent=2, default=str))
    print("=== JSON_OUTPUT_END ===")
