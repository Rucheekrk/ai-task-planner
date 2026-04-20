import sys
import json

from dotenv import load_dotenv

from apps.agent import run_agent
from apps.logger import get_logger

load_dotenv()
logger = get_logger("MAIN")


if __name__ == "__main__":
    print("Reading input from stdin... (use: python3 main.py < input.txt)\n")
    user_input = sys.stdin.read().strip()

    result = run_agent(user_input)

    logger.info(f"Intent: {result.get('plan', {}).get('intent')}")
    logger.info(f"Tasks processed: {result.get('pipeline_output', {}).get('tasks_count', 0)}")
    logger.info(f"Tool calls made: {len(result.get('tool_results', []))}")
    logger.info(f"Session summary: {result.get('output', '')}")

    print()
    print(json.dumps(result, indent=2, default=str))
