import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Single shared OpenAI client — reused across all pipeline LLM calls
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def call_llm(prompt: str) -> str:
    # Send a plain text prompt and return the raw text response
    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
        temperature=0,
    )
    return response.output_text


def call_llm_json(prompt: str) -> dict:
    # Send a prompt and parse the response as JSON.
    # All pipeline nodes expect JSON output — the prompts enforce this.
    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
        temperature=0,
    )

    raw_text = response.output_text.strip()

    # Parse and return the JSON response from the model
    return json.loads(raw_text)
