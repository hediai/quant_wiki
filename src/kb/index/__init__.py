"""Index layer: SQLite metadata + LanceDB chunks/vectors."""
from .meta import MetaStore
from .vectors import VectorStore, Hit
from .embed import Embedder, ZeroEmbedder, get_embedder

__all__ = ["MetaStore", "VectorStore", "Hit", "Embedder", "ZeroEmbedder", "get_embedder"]
