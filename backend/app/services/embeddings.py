"""本地 BGE-M3 嵌入服务，把文本转换成可计算语义相似度的向量。"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import Settings


class EmbeddingService:
    """统一模型加载与批量编码；模型实例在当前 Python 进程中缓存复用。"""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def model(self) -> SentenceTransformer:
        self.settings.ensure_directories()
        # 正常运行只读取 setup 阶段准备好的缓存，避免断网时 Hugging Face HEAD 重试阻塞检索。
        return _load_model(self.settings.embedding_model, str(self.settings.models_root), True)

    def ensure_model(self) -> None:
        self.settings.ensure_directories()
        # setup 阶段允许联网下载；与运行阶段的离线加载使用不同缓存键。
        _load_model(self.settings.embedding_model, str(self.settings.models_root), False)

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """批量编码并归一化文本向量，供 pgvector 计算余弦距离。"""
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
        """把用户问题编码成与文档片段相同维度的向量。"""
        return self.encode_documents([query])[0]


@lru_cache(maxsize=4)
def _load_model(
    model_name: str, cache_folder: str, local_files_only: bool,
) -> SentenceTransformer:
    return SentenceTransformer(
        model_name,
        cache_folder=cache_folder,
        trust_remote_code=False,
        local_files_only=local_files_only,
    )
