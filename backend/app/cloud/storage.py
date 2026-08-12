from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "application/zip": ".zip",
}


@dataclass(frozen=True, slots=True)
class StoredObjectResult:
    object_key: str
    size_bytes: int
    sha256: str


class LocalPrivateObjectStore:
    """Private filesystem object storage with tenant-scoped, non-user-derived keys."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, object_key: str) -> Path:
        if not object_key or object_key.startswith(("/", "\\")):
            raise ValueError("附件对象键无效")
        target = (self.root / object_key).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("附件对象键越过了私有存储边界") from exc
        return target

    @staticmethod
    def build_key(
        workspace_public_id: uuid.UUID,
        object_public_id: uuid.UUID,
        content_type: str,
        created_at: datetime | None = None,
    ) -> str:
        extension = CONTENT_EXTENSIONS.get(content_type)
        if extension is None:
            raise ValueError("不支持的附件媒体类型")
        moment = created_at or datetime.now().astimezone()
        return (
            f"workspaces/{workspace_public_id}/{moment:%Y/%m}/"
            f"{object_public_id.hex}{extension}"
        )

    def put_bytes(self, object_key: str, content: bytes) -> StoredObjectResult:
        target = self._resolve_key(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return StoredObjectResult(object_key=object_key, size_bytes=len(content), sha256=digest)

    def put_file(self, object_key: str, source: Path) -> StoredObjectResult:
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self._resolve_key(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temporary_name: str | None = None
        try:
            with source.open("rb") as input_file, tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                while True:
                    chunk = input_file.read(1024 * 1024)
                    if not chunk:
                        break
                    temporary.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return StoredObjectResult(object_key=object_key, size_bytes=size, sha256=digest.hexdigest())

    def path_for_read(self, object_key: str) -> Path:
        target = self._resolve_key(object_key)
        if not target.is_file():
            raise KeyError(object_key)
        return target

    def delete(self, object_key: str) -> bool:
        target = self._resolve_key(object_key)
        if not target.exists():
            return False
        target.unlink()
        return True

    def delete_workspace(self, workspace_public_id: uuid.UUID) -> bool:
        """Remove one explicitly identified tenant directory, never a shared parent."""
        target = (self.root / "workspaces" / str(workspace_public_id)).resolve()
        boundary = (self.root / "workspaces").resolve()
        try:
            target.relative_to(boundary)
        except ValueError as exc:
            raise ValueError("工作空间附件目录越过了私有存储边界") from exc
        if target == boundary:
            raise ValueError("不能删除共享附件目录")
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True
