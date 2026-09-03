from statistics import mean

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from app.ocr.base import OcrResult


class TesseractOcrEngine:
    def __init__(self, languages: str = "chi_sim+eng"):
        self.languages = languages

    def recognize(self, image: Image.Image) -> OcrResult:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
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

