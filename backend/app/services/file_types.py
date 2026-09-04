"""文件类型安全校验：组合扩展名、MIME 嗅探和 OOXML 包结构判断。"""

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import magic

from app.errors import UnsupportedFileType


@dataclass(frozen=True)
class DetectedFileType:
    extension: str
    mime_type: str


SIMPLE_TYPES = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "txt": {"text/plain"},
    "md": {"text/plain", "text/markdown"},
    "markdown": {"text/plain", "text/markdown"},
    "csv": {"text/plain", "text/csv", "application/csv"},
}
OOXML_ROOTS = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
OOXML_MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _safe_extension(original_name: str) -> str:
    name = Path(original_name).name
    if not name or name in {".", ".."}:
        raise UnsupportedFileType("文件名无效")
    extension = Path(name).suffix.lower().lstrip(".")
    if extension not in SIMPLE_TYPES and extension not in OOXML_ROOTS:
        raise UnsupportedFileType()
    return extension


def _validate_text(path: Path) -> None:
    sample = path.read_bytes()[:65_536]
    if b"\x00" in sample:
        raise UnsupportedFileType("文本文件包含无效的二进制内容")
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            sample.decode(encoding)
            return
        except UnicodeDecodeError:
            continue
    raise UnsupportedFileType("文本编码不受支持，请转换为 UTF-8 或 GB18030")


def detect_allowed_type(path: Path, original_name: str) -> DetectedFileType:
    extension = _safe_extension(original_name)
    detected_mime = magic.from_file(str(path), mime=True).lower()

    if extension in OOXML_ROOTS:
        try:
            with ZipFile(path) as archive:
                names = archive.namelist()
                if "[Content_Types].xml" not in names or not any(name.startswith(OOXML_ROOTS[extension]) for name in names):
                    raise UnsupportedFileType("Office 文件内部结构与扩展名不匹配")
        except (BadZipFile, OSError):
            raise UnsupportedFileType("Office 文件已损坏或扩展名不匹配") from None
        return DetectedFileType(extension, OOXML_MIMES[extension])

    if extension in {"txt", "md", "markdown", "csv"}:
        _validate_text(path)
        normalized = "md" if extension == "markdown" else extension
        return DetectedFileType(normalized, "text/csv" if normalized == "csv" else "text/plain")

    if detected_mime not in SIMPLE_TYPES[extension]:
        raise UnsupportedFileType("文件内容与扩展名不匹配")
    return DetectedFileType("jpg" if extension == "jpeg" else extension, detected_mime)
