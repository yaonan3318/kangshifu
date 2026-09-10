"""DOCX 解析器：提取标题层级、段落、表格（含合并单元格）与内嵌图片 OCR。"""

from pathlib import Path

from docx import Document as WordDocument

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock


class DocxParser:
    """使用 python-docx 把 Word 内容转换成统一 ParsedBlock。"""
    name = "python-docx"
    version = "2"

    def __init__(self, ocr: OcrEngine | None = None):
        self.ocr = ocr

    def parse(self, path: Path) -> list[ParsedBlock]:
        document = WordDocument(path)
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style else ""
            if style_name.lower().startswith("heading"):
                try:
                    level = int(style_name.split()[-1])
                except ValueError:
                    level = 1
                headings[:] = headings[: level - 1]
                headings.append(text)
            else:
                blocks.append(ParsedBlock(content=text, section_path=headings.copy()))
        for table_number, table in enumerate(document.tables, start=1):
            blocks.extend(self._table_blocks(table, headings, table_number))
        blocks.extend(self._image_blocks(document, headings))
        return blocks

    @staticmethod
    def _row_values(row) -> list[str]:
        values: list[str] = []
        seen = set()
        for cell in row.cells:
            # 合并单元格共享同一个 tc，跳过重复单元格避免重复文本。
            marker = id(cell._tc)
            if marker in seen:
                continue
            seen.add(marker)
            values.append(cell.text.strip())
        return values

    def _table_blocks(self, table, headings: list[str], table_number: int) -> list[ParsedBlock]:
        rows = [self._row_values(row) for row in table.rows]
        rows = [row for row in rows if any(value for value in row)]
        if not rows:
            return []
        headers = rows[0]
        output: list[ParsedBlock] = []
        for row_number, values in enumerate(rows[1:] or rows, start=2 if len(rows) > 1 else 1):
            fields = [
                f"{headers[index] if index < len(headers) and headers[index] else f'列{index + 1}'}={value}"
                for index, value in enumerate(values) if value
            ]
            if fields:
                output.append(ParsedBlock(
                    content="；".join(fields), section_path=[*headings, f"表格 {table_number}"],
                    row_start=row_number, row_end=row_number, block_type="table",
                ))
        return output

    def _image_blocks(self, document, headings: list[str]) -> list[ParsedBlock]:
        if self.ocr is None:
            return []
        output: list[ParsedBlock] = []
        try:
            from PIL import Image
            import io

            for shape in document.inline_shapes:
                if getattr(shape, "type", None) is None:
                    continue
                blip = shape._inline.graphic.graphicData.pic.blipFill.blip
                part = document.part.related_parts.get(blip.embed)
                if part is None:
                    continue
                with Image.open(io.BytesIO(part.blob)) as image:
                    result = self.ocr.recognize(image)
                if result.text.strip():
                    output.append(ParsedBlock(
                        content=result.text.strip(), section_path=headings.copy(),
                        ocr_confidence=result.confidence, block_type="image_ocr",
                    ))
        except Exception:
            return output
        return output
