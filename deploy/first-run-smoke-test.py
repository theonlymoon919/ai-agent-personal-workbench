from __future__ import annotations

import argparse
import asyncio
import secrets

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def credentials(label: str) -> tuple[str, str, str]:
    suffix = secrets.token_hex(5)
    return f"smoke_{label}_{suffix}", f"Smoke {label}", secrets.token_urlsafe(24)


async def verify_mcp(url: str, token: str) -> None:
    async with streamablehttp_client(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            if "get_workspace_overview" not in names:
                raise AssertionError("authenticated MCP tool list is incomplete")
            overview = await session.call_tool("get_workspace_overview", {})
            if overview.isError:
                raise AssertionError("authenticated MCP overview call failed")


async def run(base_url: str) -> None:
    admin_username, admin_name, admin_password = credentials("admin")
    member_username, member_name, member_password = credentials("member")
    async with httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=True) as admin:
        status = await admin.get("/api/auth/setup-status")
        status.raise_for_status()
        if status.json() != {"setup_required": True}:
            raise AssertionError("fresh database did not require initial setup")

        setup = await admin.post(
            "/api/auth/setup",
            json={"username": admin_username, "display_name": admin_name, "password": admin_password},
        )
        if setup.status_code != 201 or not setup.json()["user"]["can_invite"]:
            raise AssertionError(f"initial administrator setup failed with {setup.status_code}")
        csrf = setup.json()["csrf_token"]

        closed = await admin.get("/api/auth/setup-status")
        if closed.json() != {"setup_required": False}:
            raise AssertionError("setup endpoint did not close")
        repeated = await admin.post(
            "/api/auth/setup",
            json={"username": "another_admin", "display_name": "Another Admin", "password": secrets.token_urlsafe(24)},
        )
        if repeated.status_code != 409:
            raise AssertionError("a second initial administrator was accepted")

        invite = await admin.post(
            "/api/account/invites",
            headers={"X-CSRF-Token": csrf},
            json={"expires_in_hours": 1},
        )
        if invite.status_code != 201:
            raise AssertionError(f"administrator invitation failed with {invite.status_code}")

        task = await admin.post(
            "/api/tasks",
            headers={"X-CSRF-Token": csrf},
            json={"title": "Synthetic tenant A task", "quadrant": "important_urgent"},
        )
        if task.status_code != 201:
            raise AssertionError(f"administrator task creation failed with {task.status_code}")

        async with httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=True) as member:
            registered = await member.post(
                "/api/auth/register",
                json={
                    "invite_code": invite.json()["invite_code"],
                    "username": member_username,
                    "display_name": member_name,
                    "password": member_password,
                },
            )
            if registered.status_code != 201:
                raise AssertionError(f"invited registration failed with {registered.status_code}")
            member_csrf = registered.json()["csrf_token"]
            member_tasks = await member.get("/api/tasks")
            member_tasks.raise_for_status()
            if any(item.get("title") == "Synthetic tenant A task" for item in member_tasks.json()):
                raise AssertionError("invited tenant can read administrator task")
            agent_token = await member.post(
                "/api/account/agent-token",
                headers={"X-CSRF-Token": member_csrf},
                json={"current_password": member_password, "confirmation": "重新生成Agent令牌"},
            )
            if agent_token.status_code != 201 or not agent_token.json()["agent_token"].startswith("wba."):
                raise AssertionError(f"Agent Token creation failed with {agent_token.status_code}")
            await verify_mcp(f"{base_url}/mcp/", agent_token.json()["agent_token"])

    print("First-run smoke test passed: setup closed, invitation worked, MCP authenticated, tenant data isolated.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    args = parser.parse_args()
    asyncio.run(run(args.url.rstrip("/")))


if __name__ == "__main__":
    main()
