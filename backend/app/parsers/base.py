from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedBlock:
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
    name: str
    version: str

    def parse(self, path: Path) -> list[ParsedBlock]: ...

