from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float | None


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> OcrResult: ...

