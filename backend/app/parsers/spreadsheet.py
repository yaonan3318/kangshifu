"""XLSX/CSV 解析器：按工作表和行批次产生带位置的文本块，处理合并单元格与内嵌图片。"""

import csv
import io
from pathlib import Path
from typing import Iterable

import chardet
from openpyxl import load_workbook

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock


def _row_text(headers: list[str], values: Iterable[object]) -> str:
    fields: list[str] = []
    for index, value in enumerate(values):
        if value is None or str(value).strip() == "":
            continue
        label = headers[index] if index < len(headers) and headers[index] else f"列{index + 1}"
        fields.append(f"{label}={value}")
    return "；".join(fields)


class XlsxParser:
    name = "openpyxl"
    version = "2"

    def __init__(self, ocr: OcrEngine | None = None):
        self.ocr = ocr

    def parse(self, path: Path) -> list[ParsedBlock]:
        workbook = load_workbook(path, data_only=True, keep_links=False)
        blocks: list[ParsedBlock] = []
        try:
            for sheet in workbook.worksheets:
                merged = self._merged_values(sheet)
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    continue
                headers = [str(value).strip() if value is not None else "" for value in rows[0]]
                for row_number, values in enumerate(rows[1:], start=2):
                    filled = [
                        value if value is not None else merged.get((row_number, column + 1))
                        for column, value in enumerate(values)
                    ]
                    content = _row_text(headers, filled)
                    if content:
                        blocks.append(ParsedBlock(
                            content=content, sheet_name=sheet.title,
                            row_start=row_number, row_end=row_number,
                            section_path=[sheet.title], block_type="table",
                        ))
                blocks.extend(self._image_blocks(sheet))
        finally:
            workbook.close()
        return blocks

    @staticmethod
    def _merged_values(sheet) -> dict[tuple[int, int], object]:
        values: dict[tuple[int, int], object] = {}
        try:
            for cell_range in sheet.merged_cells.ranges:
                value = sheet.cell(cell_range.min_row, cell_range.min_col).value
                for row in range(cell_range.min_row, cell_range.max_row + 1):
                    for column in range(cell_range.min_col, cell_range.max_col + 1):
                        values[(row, column)] = value
        except Exception:
            return {}
        return values

    def _image_blocks(self, sheet) -> list[ParsedBlock]:
        if self.ocr is None:
            return []
        output: list[ParsedBlock] = []
        try:
            from PIL import Image

            for image in getattr(sheet, "_images", []):
                data = image._data() if hasattr(image, "_data") else None
                if not data:
                    continue
                with Image.open(io.BytesIO(data)) as pil_image:
                    result = self.ocr.recognize(pil_image)
                if result.text.strip():
                    output.append(ParsedBlock(
                        content=result.text.strip(), sheet_name=sheet.title,
                        section_path=[sheet.title, "图片"], ocr_confidence=result.confidence,
                        block_type="image_ocr",
                    ))
        except Exception:
            return output
        return output


class CsvParser:
    name = "csv"
    version = "1"

    def parse(self, path: Path) -> list[ParsedBlock]:
        raw = path.read_bytes()
        encoding = chardet.detect(raw).get("encoding") or "utf-8"
        text = raw.decode(encoding, errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(text.splitlines(), dialect)
        first = next(reader, None)
        if first is None:
            return []
        headers = [value.strip() for value in first]
        blocks: list[ParsedBlock] = []
        for row_number, values in enumerate(reader, start=2):
            content = _row_text(headers, values)
            if content:
                blocks.append(ParsedBlock(
                    content=content, sheet_name="CSV", row_start=row_number, row_end=row_number,
                    section_path=["CSV"], block_type="table",
                ))
        return blocks
