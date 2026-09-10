"""文本清洗与切片：按知识库配置选择固定/标题/段落/页面/表格/父子切片策略。

所有策略都控制片段长度，并用重叠内容保留跨片段语义；父片段用于后续父级扩展检索。
"""

from dataclasses import asdict, dataclass, replace
import re

from app.parsers.base import ParsedBlock

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；.!?;])")

STRATEGIES = ("fixed", "heading", "paragraph", "page", "table", "parent_child")
STRATEGY_LABELS = {
    "fixed": "固定长度切片",
    "heading": "标题层级切片",
    "paragraph": "段落切片",
    "page": "页面切片",
    "table": "表格切片",
    "parent_child": "父子切片",
}


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "fixed"
    target: int = 800
    maximum: int = 1200
    overlap: int = 100
    min_chars: int = 40
    row_batch: int = 30

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChunkingConfig":
        base = cls()
        values = asdict(base)
        if not data:
            return base
        if data.get("strategy") in STRATEGIES:
            values["strategy"] = data["strategy"]
        for name in ("target", "maximum", "overlap", "min_chars", "row_batch"):
            try:
                if data.get(name) is not None:
                    values[name] = int(data[name])
            except (TypeError, ValueError):
                continue
        # 保证参数合法：maximum >= target，overlap < maximum。
        values["target"] = max(50, values["target"])
        values["maximum"] = max(values["target"], values["maximum"])
        values["overlap"] = max(0, min(values["overlap"], values["maximum"] - 1))
        values["min_chars"] = max(0, values["min_chars"])
        values["row_batch"] = max(1, values["row_batch"])
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


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


def _merge_small(blocks: list[ParsedBlock], target: int, min_chars: int) -> list[ParsedBlock]:
    """合并过短且同章节的相邻片段，避免产生大量无意义碎片。"""
    if min_chars <= 0:
        return blocks
    merged: list[ParsedBlock] = []
    for block in blocks:
        if (
            merged
            and len(block.content) < min_chars
            and merged[-1].section_path == block.section_path
            and merged[-1].block_type == block.block_type
            and len(merged[-1].content) + len(block.content) + 2 <= target
        ):
            previous = merged[-1]
            merged[-1] = replace(previous, content=f"{previous.content}\n\n{block.content}", page_end=block.page_end or previous.page_end)
        else:
            merged.append(block)
    return merged


def _fixed(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    output: list[ParsedBlock] = []
    buffer: ParsedBlock | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer:
            output.extend(replace(buffer, content=piece) for piece in _split_long_text(buffer.content, config.maximum, config.overlap))
        buffer = None

    for block in blocks:
        structured = block.sheet_name is not None or block.slide_number is not None or block.block_type == "table"
        if structured:
            flush()
            output.extend(replace(block, content=piece) for piece in _split_long_text(block.content, config.maximum, config.overlap))
            continue
        compatible = buffer is not None and buffer.section_path == block.section_path and buffer.page_start == block.page_start
        if not compatible:
            flush()
            buffer = block
        elif len(buffer.content) + len(block.content) + 2 <= config.target:
            buffer = replace(buffer, content=f"{buffer.content}\n\n{block.content}", page_end=block.page_end or buffer.page_end)
        else:
            flush()
            buffer = block
    flush()
    return _merge_small(output, config.target, config.min_chars)


def _group_by(blocks: list[ParsedBlock], key) -> list[list[ParsedBlock]]:
    groups: list[list[ParsedBlock]] = []
    current_key = object()
    for block in blocks:
        block_key = key(block)
        if not groups or block_key != current_key:
            groups.append([block])
            current_key = block_key
        else:
            groups[-1].append(block)
    return groups


def _heading(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    output: list[ParsedBlock] = []
    for group in _group_by(blocks, lambda block: tuple(block.section_path)):
        head = group[0]
        content = "\n\n".join(block.content for block in group)
        for piece in _split_long_text(content, config.maximum, config.overlap):
            output.append(replace(head, content=piece))
    return output


def _paragraph(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    return _merge_small(blocks, config.target, config.min_chars)


def _page(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    output: list[ParsedBlock] = []
    for group in _group_by(blocks, lambda block: block.page_start):
        head = group[0]
        content = "\n\n".join(block.content for block in group)
        for piece in _split_long_text(content, config.maximum, config.overlap):
            output.append(replace(head, content=piece, page_end=group[-1].page_end or head.page_end))
    return output


def _table(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    """表格按行批次分块，避免超长表格生成过大的片段；正文仍按固定长度切片。"""
    output: list[ParsedBlock] = []
    text_buffer: list[ParsedBlock] = []
    table_buffer: list[ParsedBlock] = []

    def flush_text() -> None:
        if text_buffer:
            output.extend(_fixed(text_buffer, config))
            text_buffer.clear()

    def flush_table() -> None:
        if not table_buffer:
            return
        for index in range(0, len(table_buffer), config.row_batch):
            group = table_buffer[index:index + config.row_batch]
            head = group[0]
            output.append(replace(
                head, content="\n".join(block.content for block in group),
                row_start=head.row_start, row_end=group[-1].row_end or head.row_end,
            ))
        table_buffer.clear()

    for block in blocks:
        if block.block_type == "table" or block.sheet_name is not None:
            flush_text()
            table_buffer.append(block)
        else:
            flush_table()
            text_buffer.append(block)
    flush_text()
    flush_table()
    return output


def _parent_child(blocks: list[ParsedBlock], config: ChunkingConfig) -> list[ParsedBlock]:
    output: list[ParsedBlock] = []
    for group in _group_by(blocks, lambda block: tuple(block.section_path)):
        head = group[0]
        parent_content = "\n\n".join(block.content for block in group)
        output.append(replace(head, content=parent_content, chunk_role="parent", block_type="parent"))
        for block in group:
            for piece in _split_long_text(block.content, config.maximum, config.overlap):
                output.append(replace(block, content=piece, chunk_role="child"))
    return output


_STRATEGIES = {
    "fixed": _fixed,
    "heading": _heading,
    "paragraph": _paragraph,
    "page": _page,
    "table": _table,
    "parent_child": _parent_child,
}


def chunk_blocks(
    blocks: list[ParsedBlock],
    config: ChunkingConfig | None = None,
) -> list[ParsedBlock]:
    config = config or ChunkingConfig()
    normalized = [replace(block, content=normalize_text(block.content)) for block in blocks]
    normalized = [block for block in normalized if block.content]
    strategy = _STRATEGIES.get(config.strategy, _fixed)
    return strategy(normalized, config)
