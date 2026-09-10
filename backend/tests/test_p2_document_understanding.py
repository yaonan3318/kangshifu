"""P2-6 文档理解纯单元测试：切片策略与配置（不依赖数据库）。"""

from app.parsers.base import ParsedBlock
from app.services.chunking import (
    ChunkingConfig, _split_long_text, chunk_blocks, normalize_text,
)


def _block(content, **kwargs):
    return ParsedBlock(content=content, **kwargs)


def test_normalize_text_strips_control_and_extra_space():
    assert normalize_text("a\r\n  b\t c ") == "a\nb c"


def test_split_long_text_respects_maximum_and_overlap():
    text = "。".join(["这是一段用于测试的长句子"] * 40)
    pieces = _split_long_text(text, maximum=100, overlap=20)
    assert len(pieces) > 1
    assert all(len(piece) <= 100 for piece in pieces)


def test_chunking_config_validates_bounds():
    config = ChunkingConfig.from_dict({"strategy": "heading", "target": 10, "maximum": 5, "overlap": 999, "row_batch": 0})
    assert config.strategy == "heading"
    assert config.maximum >= config.target
    assert config.overlap < config.maximum
    assert config.row_batch >= 1
    # 未知策略回退默认。
    assert ChunkingConfig.from_dict({"strategy": "nope"}).strategy == "fixed"


def test_fixed_strategy_merges_and_splits():
    blocks = [_block("短句一", section_path=["A"]), _block("短句二", section_path=["A"])]
    config = ChunkingConfig(strategy="fixed", target=800, maximum=1200, overlap=100, min_chars=0)
    chunks = chunk_blocks(blocks, config)
    assert len(chunks) == 1
    assert "短句一" in chunks[0].content and "短句二" in chunks[0].content


def test_heading_strategy_groups_by_section_path():
    blocks = [
        _block("标题一下内容", section_path=["标题一"]),
        _block("标题一补充", section_path=["标题一"]),
        _block("标题二内容", section_path=["标题二"]),
    ]
    config = ChunkingConfig(strategy="heading")
    chunks = chunk_blocks(blocks, config)
    assert len(chunks) == 2
    assert "标题一下内容" in chunks[0].content and "标题一补充" in chunks[0].content
    assert chunks[1].section_path == ["标题二"]


def test_paragraph_strategy_keeps_paragraphs():
    blocks = [_block("第一段" * 30, section_path=["A"]), _block("第二段" * 30, section_path=["A"])]
    config = ChunkingConfig(strategy="paragraph", target=200, min_chars=0)
    chunks = chunk_blocks(blocks, config)
    assert len(chunks) == 2


def test_page_strategy_groups_by_page():
    blocks = [_block("第一页", page_start=1, page_end=1), _block("第二页", page_start=2, page_end=2)]
    config = ChunkingConfig(strategy="page")
    chunks = chunk_blocks(blocks, config)
    assert len(chunks) == 2
    assert chunks[0].page_start == 1 and chunks[1].page_start == 2


def test_table_strategy_batches_rows():
    rows = [
        _block(f"列=值{index}", sheet_name="Sheet1", row_start=index, row_end=index, block_type="table")
        for index in range(1, 8)
    ]
    config = ChunkingConfig(strategy="table", row_batch=3)
    chunks = chunk_blocks(rows, config)
    assert len(chunks) == 3
    assert chunks[0].row_start == 1 and chunks[0].row_end == 3
    assert chunks[2].row_end == 7


def test_parent_child_strategy_marks_roles():
    blocks = [
        _block("父章节第一段", section_path=["章节"]),
        _block("父章节第二段", section_path=["章节"]),
    ]
    config = ChunkingConfig(strategy="parent_child")
    chunks = chunk_blocks(blocks, config)
    parents = [chunk for chunk in chunks if chunk.chunk_role == "parent"]
    children = [chunk for chunk in chunks if chunk.chunk_role == "child"]
    assert len(parents) == 1
    assert len(children) == 2
    assert "父章节第一段" in parents[0].content and "父章节第二段" in parents[0].content
