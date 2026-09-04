"""文本清洗与切片：控制片段长度，并用重叠内容保留跨片段语义。"""

import re
from dataclasses import replace

from app.parsers.base import ParsedBlock

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；.!?;])")


def normalize_text(value: str) -> str:
    value = CONTROL_CHARACTERS.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _split_long_text(text: str, maximum: int, overlap: int) -> list[str]:
    if len(text) <= maximum:
        return [text]
    sentences = [item.strip() for item in SENTENCE_BOUNDARY.split(text) if item.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        while len(sentence) > maximum:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:maximum])
            sentence = sentence[maximum - overlap:]
        candidate = f"{current}{sentence}" if not current else f"{current}\n{sentence}"
        if len(candidate) > maximum and current:
            pieces.append(current)
            prefix = current[-overlap:] if overlap else ""
            current = f"{prefix}\n{sentence}".strip()
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_blocks(blocks: list[ParsedBlock], target: int = 800, maximum: int = 1200, overlap: int = 100) -> list[ParsedBlock]:
    normalized = [replace(block, content=normalize_text(block.content)) for block in blocks]
    normalized = [block for block in normalized if block.content]
    output: list[ParsedBlock] = []
    buffer: ParsedBlock | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer:
            for piece in _split_long_text(buffer.content, maximum, overlap):
                output.append(replace(buffer, content=piece))
        buffer = None

    for block in normalized:
        structured = block.sheet_name is not None or block.slide_number is not None
        if structured:
            flush()
            output.extend(replace(block, content=piece) for piece in _split_long_text(block.content, maximum, overlap))
            continue
        compatible = buffer is not None and buffer.section_path == block.section_path and buffer.page_start == block.page_start
        if not compatible:
            flush()
            buffer = block
        elif len(buffer.content) + len(block.content) + 2 <= target:
            buffer = replace(buffer, content=f"{buffer.content}\n\n{block.content}", page_end=block.page_end or buffer.page_end)
        else:
            flush()
            buffer = block
    flush()
    return output
