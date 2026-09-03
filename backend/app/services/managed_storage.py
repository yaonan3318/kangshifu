import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.config import Settings
from app.errors import EmptyUpload, UploadTooLarge


@dataclass(frozen=True)
class StagedFile:
    temp_path: Path
    original_name: str
    size_bytes: int
    sha256: str


class ManagedStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def stage(self, stream: BinaryIO, original_name: str) -> StagedFile:
        self.settings.ensure_directories()
        safe_name = Path(original_name.replace("\\", "/")).name.strip()
        if not safe_name or len(safe_name) > 1024 or any(ord(char) < 32 for char in safe_name):
            from app.errors import UnsupportedFileType
            raise UnsupportedFileType("文件名无效")
        temp_path = self.settings.temp_root / f"upload-{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp_path.open("xb") as target:
                while chunk := stream.read(self.settings.upload_chunk_bytes):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise UploadTooLarge()
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if size == 0:
                raise EmptyUpload()
            return StagedFile(temp_path, safe_name, size, digest.hexdigest())
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def promote(self, staged: StagedFile, document_id: uuid.UUID, extension: str) -> str:
        now = datetime.now(UTC)
        destination_dir = self.settings.originals_root / f"{now:%Y}" / f"{now:%m}"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{document_id}.{extension}"
        os.replace(staged.temp_path, destination)
        return destination.relative_to(self.settings.library_root).as_posix()

    def discard(self, staged: StagedFile) -> None:
        staged.temp_path.unlink(missing_ok=True)

    def resolve(self, relative_path: str) -> Path:
        root = self.settings.library_root.resolve()
        resolved = (root / relative_path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("managed path escapes the library root")
        return resolved

    def delete(self, relative_path: str) -> None:
        self.resolve(relative_path).unlink(missing_ok=True)
