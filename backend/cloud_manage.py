from __future__ import annotations

import argparse
import asyncio
import getpass
import json

from .app.cloud.auth import AuthService, AuthenticationError
from .app.cloud.config import CloudSettings
from .app.cloud.database import CloudDatabase


async def create_initial_admin(args: argparse.Namespace, settings: CloudSettings) -> None:
    password = getpass.getpass("管理员密码（至少 12 个字符）：")
    confirmation = getpass.getpass("再次输入管理员密码：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致")
    if len(password) < 12:
        raise SystemExit("密码至少需要 12 个字符")

    database = CloudDatabase.create(settings)
    auth = AuthService(settings)
    try:
        async with database.session_factory() as session:
            async with session.begin():
                try:
                    user = await auth.create_initial_admin(
                        session,
                        args.username,
                        args.display_name or args.username,
                        password,
                        args.timezone,
                    )
                except AuthenticationError as exc:
                    raise SystemExit(str(exc)) from exc
                user_public_id = str(user.public_id)
        print(json.dumps({"created": True, "user_id": user_public_id}, ensure_ascii=False))
    finally:
        password = ""
        confirmation = ""
        await database.close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="AI Agent Personal Workbench administration")
    subcommands = command.add_subparsers(dest="command", required=True)

    initial_admin = subcommands.add_parser(
        "create-initial-admin",
        help="Create the first administrator only when the database has no users",
    )
    initial_admin.add_argument("--username", required=True)
    initial_admin.add_argument("--display-name", default="")
    initial_admin.add_argument("--timezone", default="Asia/Shanghai")
    return command


async def main() -> None:
    args = parser().parse_args()
    settings = CloudSettings.from_env()
    if args.command == "create-initial-admin":
        await create_initial_admin(args, settings)


if __name__ == "__main__":
    asyncio.run(main())
