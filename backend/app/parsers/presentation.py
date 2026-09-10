"""PPTX 解析器：按幻灯片提取标题、文本框、表格、备注与图片 OCR。"""

import io
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock


class PptxParser:
    name = "python-pptx"
    version = "2"

    def __init__(self, ocr: OcrEngine | None = None):
        self.ocr = ocr

    def parse(self, path: Path) -> list[ParsedBlock]:
        presentation = Presentation(path)
        blocks: list[ParsedBlock] = []
        for slide_number, slide in enumerate(presentation.slides, start=1):
            texts: list[str] = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    value = shape.text.strip()
                    if value:
                        texts.append(value)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        value = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                        if value:
                            texts.append(value)
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    text = self._ocr_picture(shape)
                    if text:
                        texts.append(f"图片文字：{text}")
            try:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    texts.append(f"备注：{notes}")
            except (AttributeError, KeyError):
                pass
            if texts:
                title = slide.shapes.title.text.strip() if slide.shapes.title and slide.shapes.title.text else f"幻灯片 {slide_number}"
                blocks.append(ParsedBlock(content="\n".join(texts), slide_number=slide_number, section_path=[title]))
        return blocks

    def _ocr_picture(self, shape) -> str:
        if self.ocr is None:
            return ""
        try:
            from PIL import Image

            image = shape.image
            with Image.open(io.BytesIO(image.blob)) as pil_image:
                return self.ocr.recognize(pil_image).text.strip()
        except Exception:
            return ""
