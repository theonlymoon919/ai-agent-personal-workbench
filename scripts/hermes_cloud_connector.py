from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect


TOKEN_ENV_KEY = "MCP_PERSONAL_WORKBENCH_API_KEY"


def prompt_paths() -> tuple[Path, ...]:
    script_path = Path(__file__).resolve()
    configured = os.getenv("PERSONAL_WORKBENCH_PROMPT_PATH", "").strip()
    candidates = [
        script_path.with_name("HERMES_WORKBENCH_PROMPT.md"),
        script_path.with_name("hermes-prompt.md"),
    ]
    if configured:
        candidates.insert(0, Path(configured).expanduser())
    if len(script_path.parents) > 1:
        candidates.extend(
            (
                script_path.parents[1] / "docs" / "HERMES_WORKBENCH_PROMPT.md",
                script_path.parents[1] / "docs" / "integrations" / "hermes-prompt.md",
            )
        )
    return tuple(candidates)


def workbench_prompt() -> str:
    for prompt_path in prompt_paths():
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
            if prompt:
                return prompt
        except OSError:
            continue
    return (
        "Use only the personal_workbench MCP server for durable workbench records. "
        "Start with get_workspace_overview, claim queued jobs before processing, "
        "write only verified data, and finish claimed jobs with complete_agent_job."
    )


def hermes_home() -> Path:
    configured = os.getenv("HERMES_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    try:
        from hermes_cli.config import get_hermes_home

        return get_hermes_home()
    except ImportError:
        return Path.home() / ".hermes"


def load_secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    if direct:
        return direct
    env_file = hermes_home() / ".env"
    if env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    raise RuntimeError(f"Hermes private environment is missing {name}; run configure_hermes.py again")


def websocket_url(server_url: str) -> str:
    parsed = urlparse(server_url.strip().rstrip("/"))
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
            "The workbench origin must be an HTTPS origin without a path, query, fragment, or credentials; "
            "localhost HTTP is allowed for development"
        )
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/ws/agent", "", "", ""))


def task_prompt(job: dict) -> str:
    job_id = str(job.get("id", ""))
    job_type = str(job.get("type", ""))
    title = str(job.get("title", ""))
    return (
        workbench_prompt()
        + "\n\n## Real-time Personal Workbench job\n\n"
        + f"Job ID={job_id}; type={job_type}; title={title}. "
        "Call claim_next_agent_job, read its payload and related record, write back only verified results, "
        "then call complete_agent_job. For a health image, call load_health_image before analysis. "
        "Do not invent unreadable details or create duplicate records."
    )


def run_hermes(job: dict, command: str) -> None:
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] received job "
        f"{job.get('type', '')} / {job.get('id', '')}",
        flush=True,
    )
    result = subprocess.run(
        [command, "-z", task_prompt(job)],
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        print(f"Hermes exited with code {result.returncode}; the connector will keep listening", flush=True)


def listen(server_url: str, token: str, command: str) -> None:
    endpoint = websocket_url(server_url)
    reconnect_delay = 1
    while True:
        try:
            with connect(
                endpoint,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=20,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=1024 * 1024,
            ) as socket:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Agent job channel connected", flush=True)
                reconnect_delay = 1
                while True:
                    raw_message = socket.recv()
                    if not isinstance(raw_message, str):
                        continue
                    message = json.loads(raw_message)
                    if message.get("type") == "job.available" and isinstance(message.get("job"), dict):
                        run_hermes(message["job"], command)
        except (WebSocketException, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Agent channel interrupted "
                f"({type(exc).__name__}); retrying in {reconnect_delay}s",
                flush=True,
            )
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep Hermes connected to Personal Workbench jobs.")
    parser.add_argument("--url", required=True, help="Workbench origin, for example https://workbench.example.com")
    parser.add_argument("--hermes-command", default="hermes")
    args = parser.parse_args()
    command = shutil.which(args.hermes_command)
    if command is None:
        raise SystemExit("The Hermes command was not found")
    token = load_secret(TOKEN_ENV_KEY)
    try:
        listen(args.url, token, command)
    except KeyboardInterrupt:
        token = ""
        print("Hermes workbench connector stopped", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
