from pathlib import Path

from PIL import Image

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock


class ImageParser:
    name = "image-ocr"
    version = "1"

    def __init__(self, ocr: OcrEngine):
        self.ocr = ocr

    def parse(self, path: Path) -> list[ParsedBlock]:
        with Image.open(path) as image:
            result = self.ocr.recognize(image)
        return [ParsedBlock(content=result.text, ocr_confidence=result.confidence)] if result.text.strip() else []

