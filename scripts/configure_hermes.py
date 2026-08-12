from __future__ import annotations

import argparse
import getpass
import shutil
from datetime import datetime
from urllib.parse import urlparse

def main() -> None:
    parser = argparse.ArgumentParser(description="Connect Hermes to Personal Workbench over MCP.")
    parser.add_argument("--url", required=True, help="HTTPS MCP URL, for example https://workbench.example.com/mcp/")
    args = parser.parse_args()
    try:
        from hermes_cli.config import get_hermes_home, load_config, save_config, save_env_value
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Hermes CLI configuration support is unavailable. Run this helper from the Hermes environment."
        ) from exc
    token = getpass.getpass("Personal Workbench Agent Token (input is hidden): ").strip()
    token_parts = token.split(".")
    if len(token_parts) != 4 or token_parts[0] != "wba":
        raise SystemExit("Invalid Agent Token format; expected a token beginning with wba.")

    parsed_url = urlparse(args.url.strip())
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path.rstrip("/") != "/mcp"
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise SystemExit(
            "The MCP URL must be a complete HTTPS URL ending in /mcp/ without a query, "
            "fragment, or credentials."
        )

    hermes_home = get_hermes_home()
    config_path = hermes_home / "config.yaml"
    if config_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(config_path, config_path.with_name(f"config.yaml.workbench-{stamp}.bak"))

    env_key = "MCP_PERSONAL_WORKBENCH_API_KEY"
    save_env_value(env_key, token)
    save_env_value("PERSONAL_WORKBENCH_URL", f"{parsed_url.scheme}://{parsed_url.netloc}")
    config = load_config()
    config.setdefault("mcp_servers", {})["personal_workbench"] = {
        "url": args.url,
        "headers": {"Authorization": f"Bearer ${{{env_key}}}"},
        "timeout": 180,
        "connect_timeout": 30,
        "keepalive_interval": 120,
        "sampling": {"enabled": False},
    }
    save_config(config)
    token = ""
    print("Hermes MCP connection configured. Restart or reload Hermes to apply it.")


if __name__ == "__main__":
    main()
