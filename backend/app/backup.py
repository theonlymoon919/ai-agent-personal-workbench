from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .version import APP_VERSION


BACKUP_NAME_PATTERN = re.compile(r"^workbench-backup-\d{8}-\d{6}(?:-[a-z0-9-]+)?\.zip$")


class BackupManager:
    """Create portable backups without ever including runtime configuration or secrets."""

    def __init__(self, data_root: Path, backup_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.backup_root = backup_root.resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        try:
            self.backup_root.relative_to(self.data_root)
        except ValueError:
            pass
        else:
            raise ValueError("备份目录不能位于工作台数据目录内部")

    def _backup_path(self, name: str) -> Path:
        if not BACKUP_NAME_PATTERN.fullmatch(name):
            raise ValueError("备份文件名无效")
        target = (self.backup_root / name).resolve()
        try:
            target.relative_to(self.backup_root)
        except ValueError as exc:
            raise ValueError("备份路径无效") from exc
        return target

    def create(self, label: str = "") -> dict[str, Any]:
        suffix = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:24]
        timestamp = datetime.now().astimezone()
        unique = f"{timestamp.microsecond // 1000:03d}"
        name = f"workbench-backup-{timestamp.strftime('%Y%m%d-%H%M%S')}-{unique}{f'-{suffix}' if suffix else ''}.zip"
        target = self._backup_path(name)
        manifest = {
            "format": "personal-workbench-backup",
            "format_version": 1,
            "app_version": APP_VERSION,
            "created_at": timestamp.isoformat(timespec="seconds"),
            "contains": "Markdown、图片附件与工作台设置",
            "excludes": ["应用令牌", "运行配置", "缓存", "程序文件"],
        }
        descriptor, temporary_name = tempfile.mkstemp(prefix=".workbench-backup-", suffix=".tmp", dir=self.backup_root)
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in sorted(self.data_root.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(self.data_root)
                    archive.write(path, Path("data") / relative)
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return self.describe(target)

    def describe(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("backup-manifest.json"))
                created_at = str(manifest.get("created_at") or created_at)
        except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
            manifest = {}
        return {
            "name": path.name,
            "created_at": created_at,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "app_version": manifest.get("app_version", ""),
        }

    def list(self) -> list[dict[str, Any]]:
        backups = [self.describe(path) for path in self.backup_root.glob("workbench-backup-*.zip") if path.is_file()]
        return sorted(backups, key=lambda item: item["created_at"], reverse=True)

    def get(self, name: str) -> Path:
        target = self._backup_path(name)
        if not target.is_file():
            raise KeyError(name)
        return target

    def restore(self, name: str) -> dict[str, Any]:
        source = self.get(name)
        safety_backup = self.create("before-restore")
        restored_files = 0
        with tempfile.TemporaryDirectory(prefix="workbench-restore-") as temporary:
            extract_root = Path(temporary).resolve()
            with zipfile.ZipFile(source) as archive:
                try:
                    manifest = json.loads(archive.read("backup-manifest.json"))
                except (KeyError, json.JSONDecodeError) as exc:
                    raise ValueError("这不是有效的工作台备份") from exc
                if manifest.get("format") != "personal-workbench-backup":
                    raise ValueError("备份格式不受支持")
                for member in archive.infolist():
                    if member.filename == "backup-manifest.json" or member.is_dir():
                        continue
                    member_path = Path(member.filename)
                    if not member_path.parts or member_path.parts[0] != "data":
                        continue
                    relative = Path(*member_path.parts[1:])
                    if not relative.parts:
                        continue
                    extracted = (extract_root / relative).resolve()
                    try:
                        extracted.relative_to(extract_root)
                    except ValueError as exc:
                        raise ValueError("备份中包含不安全的路径") from exc
                    extracted.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as reader, extracted.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
            for path in extract_root.rglob("*"):
                if not path.is_file():
                    continue
                destination = self.data_root / path.relative_to(extract_root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                restored_files += 1
        return {
            "restored": True,
            "backup": self.describe(source),
            "safety_backup": safety_backup,
            "restored_files": restored_files,
            "mode": "safe_merge",
        }
