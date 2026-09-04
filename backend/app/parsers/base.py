"""所有文档解析器共享的中间数据结构与接口协议。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedBlock:
    """解析器输出的逻辑文本块，并携带原文位置和 OCR 置信度。"""
    content: str
    page_start: int | None = None
    page_end: int | None = None
    slide_number: int | None = None
    sheet_name: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    section_path: list[str] = field(default_factory=list)
    ocr_confidence: float | None = None


class DocumentParser(Protocol):
    """不同格式解析器必须实现的最小接口。"""
    name: str
    version: str

    def parse(self, path: Path) -> list[ParsedBlock]: ...
