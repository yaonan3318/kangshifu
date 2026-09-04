"""安装阶段预下载本地向量模型，避免首次检索时才等待大文件下载。"""

from app.config import get_settings
from app.services.embeddings import EmbeddingService


def main() -> None:
    """加载一次嵌入模型并打印其本地保存位置。"""
    settings = get_settings()
    print(f"Preparing local embedding model: {settings.embedding_model}")
    EmbeddingService(settings).ensure_model()
    print(f"Embedding model is ready in {settings.models_root}")


if __name__ == "__main__":
    main()
