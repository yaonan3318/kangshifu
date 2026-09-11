"""PDF 解析器：文字层优先，识别标题层级、去除页眉页脚、处理多栏/表格/图注，扫描页回退 OCR。

P2-6：无论页面是否已有文字层，都会提取内嵌图片并 OCR，再按版面距离把图片与图注关联。
"""

from collections import Counter
import io
from pathlib import Path
import statistics

import pymupdf
from PIL import Image

from app.ocr.base import OcrEngine
from app.parsers.base import ParsedBlock

CAPTION_PREFIXES = ("图", "表", "figure", "table", "fig.", "chart")
HEADING_RATIO = 1.15
HEADER_FOOTER_RATIO = 0.5
# 图片与图注的最大版面距离（PDF 点）；超过则认为无关联。
CAPTION_MAX_DISTANCE = 60.0


class PdfParser:
    name = "pymupdf+tesseract"
    version = "2"

    def __init__(self, ocr: OcrEngine, minimum_text_characters: int = 20):
        self.ocr = ocr
        self.minimum_text_characters = minimum_text_characters

    def parse(self, path: Path) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("ENCRYPTED_PDF")
            page_payloads: list[dict] = []
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if len("".join(text.split())) < self.minimum_text_characters:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    result = self.ocr.recognize(image)
                    page_payloads.append({"page": page_index, "ocr": True, "text": result.text.strip(), "confidence": result.confidence, "blocks": []})
                else:
                    page_payloads.append({
                        "page": page_index, "ocr": False, "text": text, "confidence": None,
                        "blocks": self._text_blocks(page), "tables": self._tables(page, page_index),
                        "images": self._image_blocks(page, page_index),
                        "width": page.rect.width, "height": page.rect.height,
                    })
            repeated = self._repeated_lines(page_payloads)
            for payload in page_payloads:
                if payload["ocr"]:
                    if payload["text"]:
                        blocks.append(ParsedBlock(
                            content=payload["text"], page_start=payload["page"], page_end=payload["page"],
                            ocr_confidence=payload["confidence"],
                        ))
                    continue
                blocks.extend(self._page_blocks(payload, repeated))
        return self._dedupe(blocks)

    @staticmethod
    def _text_blocks(page) -> list[dict]:
        data = page.get_text("dict")
        result: list[dict] = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines: list[str] = []
            sizes: list[float] = []
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans).strip()
                if text:
                    lines.append(text)
                sizes.extend(float(span.get("size", 0) or 0) for span in spans)
            content = "\n".join(lines).strip()
            if not content:
                continue
            result.append({
                "text": content,
                "size": max(sizes) if sizes else 0.0,
                "bbox": block.get("bbox", (0.0, 0.0, 0.0, 0.0)),
            })
        return result

    @staticmethod
    def _tables(page, page_index: int) -> list[dict]:
        tables: list[dict] = []
        finder = getattr(page, "find_tables", None)
        if finder is None:
            return tables
        try:
            for table in finder().tables:
                rows = table.extract() or []
                lines = [" | ".join(str(cell).strip() for cell in row if cell and str(cell).strip()) for row in rows]
                lines = [line for line in lines if line]
                if lines:
                    tables.append({"text": "\n".join(lines), "page": page_index, "bbox": getattr(table, "bbox", (0, 0, 0, 0))})
        except Exception:
            return []
        return tables

    @staticmethod
    def _repeated_lines(page_payloads: list[dict]) -> set[str]:
        counter: Counter[str] = Counter()
        pages = 0
        for payload in page_payloads:
            if payload["ocr"] or not payload["blocks"]:
                continue
            pages += 1
            blocks = payload["blocks"]
            top = blocks[0]["text"] if blocks else ""
            bottom = blocks[-1]["text"] if blocks else ""
            for value in (top, bottom):
                if value:
                    counter[" ".join(value.split())] += 1
        if pages < 3:
            return set()
        threshold = max(2, int(pages * HEADER_FOOTER_RATIO))
        return {text for text, count in counter.items() if count >= threshold}

    def _page_blocks(self, payload: dict, repeated: set[str]) -> list[ParsedBlock]:
        blocks = payload["blocks"]
        width = payload.get("width") or 1.0
        height = payload.get("height") or 1.0
        if not blocks and not payload.get("images"):
            return []
        weighted = [block["size"] for block in blocks for _ in range(max(1, len(block["text"])))]
        body_size = statistics.median(weighted) if weighted else 0.0
        # 去除页眉页脚：重复且位于页面上下边缘的块。
        kept = []
        for block in blocks:
            normalized = " ".join(block["text"].split())
            y0, y1 = block["bbox"][1], block["bbox"][3]
            margin = y0 < height * 0.12 or y1 > height * 0.88
            if normalized in repeated and margin:
                continue
            kept.append(block)
        ordered = self._sort_columns(kept, width)
        images, caption_block_ids = self._associate_captions(payload.get("images") or [], ordered)
        output: list[ParsedBlock] = []
        headings: list[str] = []
        heading_sizes: list[float] = []
        for block in ordered:
            if id(block) in caption_block_ids:
                continue
            text = block["text"]
            if self._is_heading(block, body_size):
                while heading_sizes and heading_sizes[-1] >= block["size"]:
                    heading_sizes.pop()
                    headings.pop()
                headings.append(text)
                heading_sizes.append(block["size"])
                continue
            block_type = "caption" if text.lower().startswith(CAPTION_PREFIXES) else "text"
            output.append(ParsedBlock(
                content=text, page_start=payload["page"], page_end=payload["page"],
                section_path=headings.copy(), block_type=block_type,
            ))
        for table in payload.get("tables", []):
            output.append(ParsedBlock(
                content=table["text"], page_start=table["page"], page_end=table["page"],
                section_path=[*headings, "表格"], block_type="table",
            ))
        for image, caption in images:
            content = f"{caption}\n{image['text']}" if caption else image["text"]
            output.append(ParsedBlock(
                content=content, page_start=payload["page"], page_end=payload["page"],
                section_path=headings.copy(), block_type="image", ocr_confidence=image.get("confidence"),
            ))
        return output

    def _image_blocks(self, page, page_index: int) -> list[dict]:
        """提取页面内嵌图片并 OCR；文字型 PDF 也会处理，不再只对整页 OCR。"""
        images: list[dict] = []
        try:
            data = page.get_text("dict")
        except Exception:
            return images
        for block in data.get("blocks", []):
            if block.get("type") != 1:
                continue
            raw = block.get("image")
            if not raw:
                continue
            try:
                image = Image.open(io.BytesIO(raw))
                result = self.ocr.recognize(image)
            except Exception:
                continue
            text = (result.text or "").strip()
            if not text:
                continue
            images.append({
                "bbox": block.get("bbox", (0.0, 0.0, 0.0, 0.0)),
                "text": text, "confidence": result.confidence, "page": page_index,
            })
        return images

    @staticmethod
    def _associate_captions(images: list[dict], blocks: list[dict]) -> tuple[list[tuple[dict, str | None]], set[int]]:
        """按版面距离把图片与最近的图注候选关联；返回 (图片, 图注) 与被占用的图注块。"""
        caption_block_ids: set[int] = set()
        results: list[tuple[dict, str | None]] = []
        for image in images:
            ix0, iy0, ix1, iy1 = image["bbox"]
            best_index: int | None = None
            best_distance = CAPTION_MAX_DISTANCE
            for index, block in enumerate(blocks):
                if id(block) in caption_block_ids:
                    continue
                text = block["text"].strip()
                if not text.lower().startswith(CAPTION_PREFIXES):
                    continue
                bx0, by0, bx1, by1 = block["bbox"]
                horizontal = min(ix1, bx1) - max(ix0, bx0)
                if horizontal <= 0:
                    continue
                vertical = max(0.0, max(iy0 - by1, by0 - iy1))
                if vertical < best_distance:
                    best_distance = vertical
                    best_index = index
            caption = None
            if best_index is not None:
                caption_block_ids.add(id(blocks[best_index]))
                caption = blocks[best_index]["text"].strip()
            results.append((image, caption))
        return results, caption_block_ids

    @staticmethod
    def _is_heading(block: dict, body_size: float) -> bool:
        if body_size <= 0 or block["size"] <= 0:
            return False
        return block["size"] > body_size * HEADING_RATIO and len(block["text"]) <= 80

    @staticmethod
    def _sort_columns(blocks: list[dict], width: float) -> list[dict]:
        mid = width / 2
        left = [block for block in blocks if block["bbox"][0] < mid]
        right = [block for block in blocks if block["bbox"][0] >= mid]
        if len(left) >= 2 and len(right) >= 2:
            return sorted(left, key=lambda item: item["bbox"][1]) + sorted(right, key=lambda item: item["bbox"][1])
        return sorted(blocks, key=lambda item: item["bbox"][1])

    @staticmethod
    def _dedupe(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
        seen: set[str] = set()
        output: list[ParsedBlock] = []
        for block in blocks:
            key = " ".join(block.content.split())
            if key and key in seen:
                continue
            seen.add(key)
            output.append(block)
        return output
