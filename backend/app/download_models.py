from app.config import get_settings
from app.services.embeddings import EmbeddingService


def main() -> None:
    settings = get_settings()
    print(f"Preparing local embedding model: {settings.embedding_model}")
    EmbeddingService(settings).ensure_model()
    print(f"Embedding model is ready in {settings.models_root}")


if __name__ == "__main__":
    main()
