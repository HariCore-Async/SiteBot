import threading

from .config import settings

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    with _lock:
        return [v.tolist() for v in _get_model().passage_embed(texts, batch_size=32)]


def embed_query(text: str) -> list[float]:
    with _lock:
        return next(iter(_get_model().query_embed(text))).tolist()


def warm_up() -> None:
    embed_query("warm up")
