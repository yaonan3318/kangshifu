from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class UnsupportedFileType(AppError):
    def __init__(self, message: str = "文件格式不受支持"):
        super().__init__("UNSUPPORTED_FILE_TYPE", message, 415)


class UploadTooLarge(AppError):
    def __init__(self):
        super().__init__("UPLOAD_TOO_LARGE", "文件超过 200 MB 上限", 413)


class EmptyUpload(AppError):
    def __init__(self):
        super().__init__("EMPTY_UPLOAD", "不能上传空文件", 400)


class DuplicateDocument(AppError):
    def __init__(self, document_id: str):
        super().__init__("DUPLICATE_DOCUMENT", "相同内容的文件已存在", 409, {"document_id": document_id})


class DocumentNotFound(AppError):
    def __init__(self):
        super().__init__("DOCUMENT_NOT_FOUND", "文档不存在", 404)


class DocumentAlreadyProcessing(AppError):
    def __init__(self):
        super().__init__("DOCUMENT_ALREADY_PROCESSING", "文档已经在处理队列中", 409)
