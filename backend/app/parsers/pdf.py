from pathlib import Path

import fitz
from PIL import Image

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock


class PdfParser:
    name = "pymupdf+tesseract"
    version = "1"

    def __init__(self, ocr: OcrEngine, minimum_text_characters: int = 20):
        self.ocr = ocr
        self.minimum_text_characters = minimum_text_characters

    def parse(self, path: Path) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError("ENCRYPTED_PDF")
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                confidence = None
                if len("".join(text.split())) < self.minimum_text_characters:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    result = self.ocr.recognize(image)
                    text, confidence = result.text.strip(), result.confidence
                if text:
                    blocks.append(ParsedBlock(content=text, page_start=page_index, page_end=page_index, ocr_confidence=confidence))
        return blocks

