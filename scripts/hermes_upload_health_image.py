from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import uuid
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from .hermes_cloud_connector import TOKEN_ENV_KEY, load_secret
except ImportError:  # Direct execution: python scripts/hermes_upload_health_image.py
    from hermes_cloud_connector import TOKEN_ENV_KEY, load_secret


MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def public_result(result: dict) -> dict:
    record_id = result.get("id")
    if not record_id:
        raise ValueError("Personal Workbench did not return a health record identifier")
    return {
        "ok": True,
        "record_id": record_id,
        "kind": result.get("kind"),
        "record_date": result.get("record_date"),
        "analysis_status": result.get("analysis_status"),
    }


def workbench_origin(value: str) -> str:
    parsed = urlparse(value.strip().rstrip("/"))
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (
        not parsed.hostname
        or (parsed.scheme != "https" and not local_http)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "The upload origin must be an HTTPS origin without a path, query, fragment, or credentials; "
            "localhost HTTP is allowed for development"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def multipart_body(path: Path, record_date: str, meal_slot: str) -> tuple[bytes, str]:
    content = path.read_bytes()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Image must not exceed 15 MB")
    if not content:
        raise ValueError("Image file is empty")
    boundary = f"workbench-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blocks: list[bytes] = []

    def field(name: str, value: str) -> None:
        blocks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    field("record_date", record_date)
    if meal_slot:
        field("meal_slot", meal_slot)
    safe_name = path.name.replace('"', "")[:255]
    blocks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(blocks), boundary


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a health image to the token owner's private workspace.")
    parser.add_argument("--kind", required=True, choices=("meal", "weight", "exercise"))
    parser.add_argument("--file", required=True, dest="file_path")
    parser.add_argument("--record-date", default=date.today().isoformat())
    parser.add_argument(
        "--meal-slot",
        default="",
        choices=("", "breakfast", "lunch", "afternoon_tea", "dinner", "snack", "late_night"),
    )
    parser.add_argument("--url", default=os.getenv("PERSONAL_WORKBENCH_URL", ""))
    args = parser.parse_args()

    path = Path(args.file_path).expanduser().resolve()
    if not path.is_file():
        raise SystemExit("Image file was not found")
    try:
        date.fromisoformat(args.record_date)
        origin = workbench_origin(args.url)
        token = load_secret(TOKEN_ENV_KEY)
        body, boundary = multipart_body(path, args.record_date, args.meal_slot)
        digest = hashlib.sha256(
            path.read_bytes() + f"|{args.kind}|{args.record_date}|{args.meal_slot}".encode()
        ).hexdigest()
        request = Request(
            f"{origin}/api/agent/uploads/{args.kind}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": f"agent-upload:{digest}"[:160],
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", "upload failed")
        except (ValueError, UnicodeDecodeError):
            detail = "upload failed"
        raise SystemExit(f"Personal Workbench rejected the upload: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise SystemExit("Could not connect to Personal Workbench") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    token = ""
    print(json.dumps(public_result(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
