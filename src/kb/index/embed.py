"""Lazy embedder: bge-m3 when available, deterministic hash fallback otherwise.

Hash fallback keeps the index/search pipeline runnable without GPU/torch — useful
for smoke tests and CI. Real evaluation uses the bge embedder.
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import Iterable, Protocol, Sequence

log = logging.getLogger(__name__)

DEFAULT_DIM = 1024  # bge-m3 dim; hash fallback uses the same size


class Embedder(Protocol):
    name: str
    dim: int
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class ZeroEmbedder:
    """Deterministic hash-based pseudo-embeddings. Cosine similarity is meaningful
    enough for smoke tests; not for real semantic retrieval."""

    def __init__(self, dim: int = DEFAULT_DIM, name: str = "hash-fallback"):
        self.dim = dim
        self.name = name

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self.dim
            # Map every token-ish to a bucket via SHA1.
            for token in (t or "").split():
                h = hashlib.sha1(token.encode("utf-8")).digest()
                # Use first 8 bytes -> two indices and signs.
                idx = int.from_bytes(h[:4], "big") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                vec[idx] += sign
            # L2 normalise for cosine.
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class BGEEmbedder:
    name = "bge-m3"

    def __init__(self, model: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._st = SentenceTransformer(model)
        self.dim = self._st.get_sentence_embedding_dimension() or DEFAULT_DIM

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        arr = self._st.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return arr.tolist()


def get_embedder(prefer: str = "auto") -> Embedder:
    if prefer in ("hash", "fallback", "zero"):
        return ZeroEmbedder()
    try:
        return BGEEmbedder()
    except Exception as exc:
        log.warning("BGEEmbedder unavailable (%s); falling back to hash embedder.", exc)
        return ZeroEmbedder()
