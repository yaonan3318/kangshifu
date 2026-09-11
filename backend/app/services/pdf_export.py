"""回答 PDF 导出：在服务端完成中文排版和分页。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

import pymupdf


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_X = 48
MARGIN_TOP = 54
MARGIN_BOTTOM = 48
BODY_SIZE = 11
LINE_HEIGHT = 18


def _plain_text(value: str) -> str:
    """保留段落结构，同时去掉影响纯文本 PDF 阅读的常见 Markdown 标记。"""
    value = re.sub(r"```[^\n]*\n?", "", value)
    value = value.replace("```", "")
    value = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return value.strip()


def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1


def _wrap(text: str, max_units: int = 86) -> Iterable[str]:
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            yield ""
            continue
        line: list[str] = []
        units = 0
        for char in paragraph:
            width = _char_width(char)
            if line and units + width > max_units:
                yield "".join(line)
                line = []
                units = 0
            line.append(char)
            units += width
        yield "".join(line)


def _location(source: dict) -> str:
    direct = str(source.get("location_text") or "").strip()
    if direct:
        return direct
    snapshot = source.get("location_snapshot") or {}
    if snapshot.get("page") is not None:
        return f"第 {snapshot['page']} 页"
    if snapshot.get("slide") is not None:
        return f"第 {snapshot['slide']} 页幻灯片"
    if snapshot.get("sheet"):
        return f"工作表 {snapshot['sheet']}"
    sequence = snapshot.get("sequence")
    return f"片段 {sequence}" if sequence is not None else ""


def build_answer_pdf(*, question: str, answer: str, sources: list[dict]) -> bytes:
    """把一个问答及其引用生成为可直接下载的 A4 PDF。"""
    document = pymupdf.open()
    page = None
    y = MARGIN_TOP

    def add_page():
        nonlocal page, y
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_font(fontname="china-s")
        y = MARGIN_TOP

    def write_lines(text: str, *, size: float = BODY_SIZE, gap_after: float = 8):
        nonlocal y
        assert page is not None
        for line in _wrap(text):
            if y > PAGE_HEIGHT - MARGIN_BOTTOM:
                add_page()
            page.insert_text((MARGIN_X, y), line or " ", fontname="china-s", fontsize=size, color=(0.08, 0.13, 0.22))
            y += LINE_HEIGHT if size <= BODY_SIZE else LINE_HEIGHT + 4
        y += gap_after

    add_page()
    write_lines("康师傅知识助手", size=18, gap_after=12)
    write_lines(f"问题：{_plain_text(question)}", size=12, gap_after=12)
    write_lines("回答", size=14, gap_after=6)
    write_lines(_plain_text(answer), gap_after=14)
    if sources:
        write_lines("引用来源", size=14, gap_after=6)
        for source in sources:
            number = source.get("citation_number", "-")
            name = source.get("document_name") or "未命名资料"
            location = _location(source)
            write_lines(f"[{number}] {name}{f' · {location}' if location else ''}", gap_after=2)

    content = document.tobytes(garbage=4, deflate=True)
    document.close()
    return content
