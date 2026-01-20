import logging
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


def load_or_download_model(model_name: str, local_dir: Path) -> SentenceTransformer:
    """
    Load a SentenceTransformer model from local_dir if it exists,
    otherwise download from Hugging Face and save locally.
    """
    try:
        if local_dir.exists() and any(local_dir.iterdir()):
            logger.info(f"Loading model from local directory: {local_dir}")
            return SentenceTransformer(str(local_dir / model_name), cache_folder=str(local_dir.absolute()))
    except Exception:
        logger.info(f"Local model not found. Downloading '{model_name}' from Hugging Face...")

    m = SentenceTransformer(model_name, cache_folder=str(local_dir.absolute()))
    logger.info(f"Saving model to local directory: {local_dir}")
    local_dir.mkdir(parents=True, exist_ok=True)
    m.save(str(local_dir / model_name))

    return m


model_name = 'BAAI/bge-small-en-v1.5'
# model_name = 'all-MiniLM-L6-v2'
model_base_path = Path(__file__).parent.parent.parent.parent / "models"
model = load_or_download_model(model_name, model_base_path)


def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity between two vectors."""
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


def get_similarity(str1: str, str2: str):
    embeddings = model.encode([str1, str2], normalize_embeddings=True)

    similarity = cosine_similarity(embeddings[0], embeddings[1])
    logger.debug(f"Similarity is {similarity}. checked strings:\n{str1}\n{str2}")
    return similarity


def get_similarity_alternatives(str1: str, alternatives: list[str]):
    max_similarity = 0
    string_with_max_similarity = ""
    for alternative in alternatives:
        similarity = get_similarity(str1, alternative)
        if max_similarity < similarity:
            max_similarity = similarity
            string_with_max_similarity = alternative

    logger.debug(
        f"Similarity is {max_similarity}. checked strings:\n{str1}\n {','.join(alternatives)}"
    )
    return max_similarity, string_with_max_similarity
