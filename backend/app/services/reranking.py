"""可选本地 CrossEncoder 精排，任何失败都显式降级到 RRF。"""

from dataclasses import dataclass
from functools import lru_cache
import math

from sentence_transformers import CrossEncoder

from app.config import Settings


@dataclass(frozen=True)
class RerankOutcome:
    scores: list[float] | None
    warning: str | None = None


class Reranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rerank(self, query: str, texts: list[str]) -> RerankOutcome:
        if not self.settings.rerank_enabled or not texts:
            return RerankOutcome(None)
        try:
            model = _load_reranker(self.settings.rerank_model, str(self.settings.models_root))
            raw = model.predict(
                [(query, text[: self.settings.rerank_max_chars]) for text in texts],
                batch_size=self.settings.rerank_batch_size,
                show_progress_bar=False,
            )
            return RerankOutcome([_sigmoid(float(value)) for value in raw])
        except Exception:
            return RerankOutcome(None, "本地精排模型不可用，本次已自动降级为混合检索")

    def ensure_model(self) -> None:
        _load_reranker(self.settings.rerank_model, str(self.settings.models_root))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


@lru_cache(maxsize=1)
def _load_reranker(model_name: str, cache_folder: str) -> CrossEncoder:
    return CrossEncoder(model_name, cache_folder=cache_folder, trust_remote_code=False)
