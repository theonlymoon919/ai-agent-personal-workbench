from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}–{maximum} 之间")
    return value


def _public_origin(value: str) -> str:
    origin = value.strip().rstrip("/")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("WORKBENCH_PUBLIC_ORIGIN 不是有效地址") from exc
    local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    secure = parsed.scheme == "https"
    local_development = parsed.scheme == "http" and local_host
    if (
        not parsed.hostname
        or not (secure or local_development)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("WORKBENCH_PUBLIC_ORIGIN 必须是 HTTPS 源地址；本机开发可使用 localhost")
    return origin


@dataclass(frozen=True, slots=True)
class CloudSettings:
    database_url: str
    token_pepper: str
    data_root: Path
    public_origin: str
    secure_cookies: bool = True
    session_days: int = 30
    database_pool_size: int = 3
    database_max_overflow: int = 2
    session_cookie_name: str = "workbench_session"
    csrf_cookie_name: str = "workbench_csrf"

    @classmethod
    def from_env(cls) -> "CloudSettings":
        database_url = os.getenv("WORKBENCH_DATABASE_URL", "").strip()
        if not database_url:
            host = os.getenv("WORKBENCH_DB_HOST", "postgres").strip()
            port = os.getenv("WORKBENCH_DB_PORT", "5432").strip()
            user = os.getenv("WORKBENCH_DB_USER", "workbench_runtime").strip()
            password = os.getenv("WORKBENCH_DB_PASSWORD", "").strip()
            database = os.getenv("WORKBENCH_DB_NAME", "workbench").strip()
            if not password:
                raise ValueError("云端模式缺少 WORKBENCH_DB_PASSWORD")
            from sqlalchemy import URL

            database_url = URL.create(
                "postgresql+psycopg",
                username=user,
                password=password,
                host=host,
                port=int(port),
                database=database,
            ).render_as_string(hide_password=False)

        pepper = os.getenv("WORKBENCH_TOKEN_PEPPER", "").strip()
        if len(pepper) < 32:
            raise ValueError("WORKBENCH_TOKEN_PEPPER 至少需要 32 个字符")

        public_origin = _public_origin(os.getenv("WORKBENCH_PUBLIC_ORIGIN", ""))

        data_root = Path(os.getenv("WORKBENCH_CLOUD_DATA_ROOT", "/data/objects")).expanduser().resolve()
        return cls(
            database_url=database_url,
            token_pepper=pepper,
            data_root=data_root,
            public_origin=public_origin,
            secure_cookies=_env_bool("WORKBENCH_SECURE_COOKIES", True),
            session_days=_env_int("WORKBENCH_SESSION_DAYS", 30, 1, 180),
            database_pool_size=_env_int("WORKBENCH_DB_POOL_SIZE", 3, 1, 20),
            database_max_overflow=_env_int("WORKBENCH_DB_MAX_OVERFLOW", 2, 0, 20),
        )
