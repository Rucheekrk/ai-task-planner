from sentence_transformers import SentenceTransformer

# Load model once (global)
model = SentenceTransformer("all-MiniLM-L6-v2")


def get_embedding(text: str) -> list:
    """
    Convert text into embedding vector (length 384)
    """
    if not text:
        return None

    embedding = model.encode(text)
    return embedding.tolist()