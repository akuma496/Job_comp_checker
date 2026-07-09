import hashlib

import numpy as np

from config import settings
from db.connection import get_conn

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model)
    return _model


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts, using an on-disk cache (embedding_cache table) keyed by
    text hash so re-matching the same resume against many jobs doesn't recompute
    resume-side embeddings repeatedly."""
    if not texts:
        return np.empty((0, 384), dtype=np.float32)

    hashes = [_hash_text(t) for t in texts]
    cached: dict[str, np.ndarray] = {}
    with get_conn() as conn:
        placeholders = ",".join("?" * len(hashes))
        rows = conn.execute(
            f"SELECT text_hash, embedding FROM embedding_cache WHERE text_hash IN ({placeholders})",
            hashes,
        ).fetchall()
        for row in rows:
            cached[row["text_hash"]] = np.frombuffer(row["embedding"], dtype=np.float32)

    missing_idx = [i for i, h in enumerate(hashes) if h not in cached]
    if missing_idx:
        model = _get_model()
        missing_texts = [texts[i] for i in missing_idx]
        new_embeddings = model.encode(missing_texts, convert_to_numpy=True, normalize_embeddings=True).astype(
            np.float32
        )
        with get_conn() as conn:
            for i, embedding in zip(missing_idx, new_embeddings):
                text_hash = hashes[i]
                cached[text_hash] = embedding
                conn.execute(
                    "INSERT OR IGNORE INTO embedding_cache (text_hash, text, embedding) VALUES (?, ?, ?)",
                    (text_hash, texts[i], embedding.tobytes()),
                )

    return np.stack([cached[h] for h in hashes])


def max_cosine_similarity(query_embedding: np.ndarray, candidate_embeddings: np.ndarray) -> tuple[float, int]:
    """Returns (best similarity score, index of best-matching candidate). Embeddings
    must already be normalized (embed_texts does this), so cosine similarity is a dot product."""
    if candidate_embeddings.shape[0] == 0:
        return 0.0, -1
    scores = candidate_embeddings @ query_embedding
    best_idx = int(np.argmax(scores))
    return float(scores[best_idx]), best_idx
