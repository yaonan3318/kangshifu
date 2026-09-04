"""基于本机 Tesseract 的中英文图片文字识别实现。"""

from statistics import mean

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from app.ocr.base import OcrResult


class TesseractOcrEngine:
    """规范化图片后调用 pytesseract，并把词结果重新组织成文本行。"""
    def __init__(self, languages: str = "chi_sim+eng"):
        self.languages = languages

    def recognize(self, image: Image.Image) -> OcrResult:
        """识别一张 PIL 图片，同时统计有效词的平均置信度。"""
        # EXIF 方向常见于手机照片，先矫正方向可避免整页文字被横向识别。
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        # 限制超大图片尺寸，避免 OCR 瞬时占用过多内存。
        if max(normalized.size) > 5000:
            normalized.thumbnail((5000, 5000))
        data = pytesseract.image_to_data(normalized, lang=self.languages, output_type=Output.DICT, config="--psm 6")
        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        for index, raw_text in enumerate(data["text"]):
            text = raw_text.strip()
            if not text:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(text)
            try:
                confidence = float(data["conf"][index])
                if confidence >= 0:
                    confidences.append(confidence / 100.0)
            except (TypeError, ValueError):
                pass
        return OcrResult("\n".join(" ".join(words) for words in lines.values()), mean(confidences) if confidences else None)
