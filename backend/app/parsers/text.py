"""TXT/Markdown 解析器：检测编码并按标题或文本段落提取内容。"""

import re
from pathlib import Path

import chardet

from app.parsers.base import ParsedBlock


class TextParser:
    name = "text"
    version = "1"

    def __init__(self, markdown: bool = False):
        self.markdown = markdown

    def parse(self, path: Path) -> list[ParsedBlock]:
        raw = path.read_bytes()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        text = raw.decode(encoding, errors="replace")
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        paragraphs: list[str] = []

        def flush() -> None:
            content = "\n\n".join(paragraphs).strip()
            if content:
                blocks.append(ParsedBlock(content=content, section_path=headings.copy()))
            paragraphs.clear()

        for paragraph in re.split(r"\n\s*\n", text):
            stripped = paragraph.strip()
            heading = re.match(r"^(#{1,6})\s+(.+)$", stripped) if self.markdown else None
            if heading:
                flush()
                level = len(heading.group(1))
                headings[:] = headings[: level - 1]
                headings.append(heading.group(2).strip())
            elif stripped:
                paragraphs.append(stripped)
        flush()
        return blocks
