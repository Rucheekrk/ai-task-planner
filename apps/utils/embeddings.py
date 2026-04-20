from sentence_transformers import SentenceTransformer

# Load the embedding model once at module import time so it is shared across all calls.
# all-MiniLM-L6-v2 produces 384-dimensional vectors — matches the task_embedding column in Postgres.
model = SentenceTransformer("all-MiniLM-L6-v2")


def get_embedding(text: str) -> list:
    # Return None for empty input — the DB column allows NULL and pgvector skips NULL rows
    if not text:
        return None

    # Encode text to a 384-dim float vector, then convert to a plain Python list
    # so it can be serialized to JSON and passed to psycopg2 as a pgvector value
    embedding = model.encode(text)
    return embedding.tolist()
