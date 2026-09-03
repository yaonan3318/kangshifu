from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import Settings


class EmbeddingService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def model(self) -> SentenceTransformer:
        self.settings.ensure_directories()
        return _load_model(self.settings.embedding_model, str(self.settings.models_root))

    def ensure_model(self) -> None:
        _ = self.model

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            batch_size=self.settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def encode_query(self, query: str) -> list[float]:
        return self.encode_documents([query])[0]


@lru_cache(maxsize=2)
def _load_model(model_name: str, cache_folder: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, cache_folder=cache_folder, trust_remote_code=False)
