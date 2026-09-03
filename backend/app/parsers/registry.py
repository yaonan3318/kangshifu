from app.ocr.base import OcrEngine
from app.parsers.base import DocumentParser
from app.parsers.docx import DocxParser
from app.parsers.image import ImageParser
from app.parsers.pdf import PdfParser
from app.parsers.presentation import PptxParser
from app.parsers.spreadsheet import CsvParser, XlsxParser
from app.parsers.text import TextParser


class ParserRegistry:
    def __init__(self, ocr: OcrEngine):
        self.parsers: dict[str, DocumentParser] = {
            "pdf": PdfParser(ocr),
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "pptx": PptxParser(),
            "txt": TextParser(),
            "md": TextParser(markdown=True),
            "csv": CsvParser(),
            "png": ImageParser(ocr),
            "jpg": ImageParser(ocr),
        }

    def get(self, extension: str) -> DocumentParser:
        try:
            return self.parsers[extension.lower()]
        except KeyError:
            raise ValueError(f"UNSUPPORTED_PARSER:{extension}") from None

