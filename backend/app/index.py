from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class MarkdownIndex:
    """A disposable SQLite index. Markdown remains the source of truth."""

    def __init__(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / "workbench-index.sqlite3"
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY,
                    record_type TEXT,
                    title TEXT,
                    updated_at TEXT,
                    mtime_ns INTEGER NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def rebuild(self, records: Iterable[dict]) -> int:
        rows = list(records)
        connection = self._connect()
        try:
            connection.execute("DELETE FROM documents")
            connection.executemany(
                "INSERT INTO documents(path, record_type, title, updated_at, mtime_ns) VALUES(?, ?, ?, ?, ?)",
                [
                    (
                        item["path"],
                        item.get("type", "note"),
                        item.get("title", ""),
                        item.get("updated_at", ""),
                        item["mtime_ns"],
                    )
                    for item in rows
                ],
            )
            connection.commit()
        finally:
            connection.close()
        return len(rows)

    def status(self) -> dict:
        connection = self._connect()
        try:
            count = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
        finally:
            connection.close()
        return {"documents": count, "path": str(self.path)}
