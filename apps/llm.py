import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def call_llm(prompt: str) -> str:
    # LLM Call: return raw text response
    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
    )
    return response.output_text


def call_llm_json(prompt: str) -> dict:
    # LLM Call: return parsed JSON response
    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
    )

    raw_text = response.output_text.strip()

    # Parse JSON safely
    return json.loads(raw_text)