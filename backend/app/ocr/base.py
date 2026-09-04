"""OCR 抽象协议，使解析器不依赖具体识别引擎。"""

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    """OCR 文字及可选的平均置信度（0 到 1）。"""
    text: str
    confidence: float | None


class OcrEngine(Protocol):
    """任何 OCR 实现只需提供 recognize 方法即可被图片/PDF 解析器使用。"""
    def recognize(self, image: Image.Image) -> OcrResult: ...
