import sys
import json

from dotenv import load_dotenv

from apps.agent import run_agent
from apps.logger import get_logger

# Load environment variables from .env (OPENAI_API_KEY, DB_*, MCP_SERVER_URL)
load_dotenv()
logger = get_logger("MAIN")


if __name__ == "__main__":
    print("Reading input from stdin... (use: python3 main.py < input.txt)\n")

    # Read full input from stdin — supports piped files or interactive typing
    user_input = sys.stdin.read().strip()

    # Run the top-level ReAct agent (intent classification → pipeline → MCP tools)
    result = run_agent(user_input)

    # Log high-level outcome for monitoring
    logger.info(f"Intent: {result.get('plan', {}).get('intent')}")
    logger.info(f"Tasks processed: {result.get('pipeline_output', {}).get('tasks_count', 0)}")
    logger.info(f"Tool calls made: {len(result.get('tool_results', []))}")
    logger.info(f"Session summary: {result.get('output', '')}")

    print()
    print("=== JSON_OUTPUT_BEGIN ===")
    print(json.dumps(result, indent=2, default=str))
    print("=== JSON_OUTPUT_END ===")
