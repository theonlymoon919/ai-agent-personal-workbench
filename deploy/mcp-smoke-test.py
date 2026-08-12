from __future__ import annotations

import argparse
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url: str, token: str) -> None:
    async with streamablehttp_client(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {
                "get_workspace_overview",
                "claim_next_agent_job",
                "complete_agent_job",
                "load_health_image",
                "create_finance_transaction",
                "list_finance_transactions",
                "delete_finance_transaction",
                "restore_finance_transaction",
                "list_finance_budgets",
                "delete_finance_budget",
                "save_generated_learning_plan",
                "save_suggestion",
            }
            if not required.issubset(names):
                raise AssertionError(f"missing MCP tools: {sorted(required - names)}")
            overview = await session.call_tool("get_workspace_overview", {})
            if overview.isError:
                raise AssertionError("authenticated overview tool returned an error")
            print(
                json.dumps(
                    {
                        "passed": True,
                        "tool_count": len(names),
                        "required_tools_present": True,
                        "workspace_overview_authenticated": True,
                    }
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    token = os.environ.get("MCP_PERSONAL_WORKBENCH_API_KEY", "").strip()
    if not token:
        raise SystemExit("MCP_PERSONAL_WORKBENCH_API_KEY is required")
    asyncio.run(run(args.url, token))


if __name__ == "__main__":
    main()
