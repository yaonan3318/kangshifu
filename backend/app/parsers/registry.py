"""解析器注册表：根据已经验证过的文件扩展名选择实现。"""

from app.ocr.base import OcrEngine
from app.parsers.base import DocumentParser
from app.parsers.docx import DocxParser
from app.parsers.image import ImageParser
from app.parsers.pdf import PdfParser
from app.parsers.presentation import PptxParser
from app.parsers.spreadsheet import CsvParser, XlsxParser
from app.parsers.text import TextParser


class ParserRegistry:
    """集中维护扩展名到解析器实例的映射，避免业务层出现格式判断链。"""
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
