from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


MANAGED_START = "<!-- PERSONAL_WORKBENCH_MANAGED_START -->"
MANAGED_END = "<!-- PERSONAL_WORKBENCH_MANAGED_END -->"
MANAGED_SOUL_BLOCK = f"""{MANAGED_START}
## AI Agent 个人工作台

当用户提到个人工作台、任务/项目、日历、健康、学习计划、书影音、热点或财务时，先调用 `skill_view(name=\"personal-workbench\")`，再按技能使用 `personal_workbench` MCP。旧的 `127.0.0.1:8787` 工作台已经退役，禁止访问、启动或重新迁移。

当用户从聊天端发送饮食、体重或运动图片并明确要求保存时，不要直接回答“无法上传”。先从当前消息的附件说明中取得真实本地缓存路径，再按 `personal-workbench` 技能调用官方上传桥接并验证 `record_id`。如果当前聊天端没有提供缓存路径，要准确说明阻塞在附件路径交接，而不是声称工作台不支持图片。

技能、记忆和回复中不得保存或展示账号密码、Agent Token、私钥或用户隐私。
{MANAGED_END}"""


def _validate_skill(skill_path: Path) -> None:
    content = skill_path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("Hermes 技能缺少有效 frontmatter")
    match = re.search(r"\n---\s*\n", content[4:])
    if match is None:
        raise ValueError("Hermes 技能 frontmatter 未闭合")
    frontmatter = content[4 : match.start() + 4]
    if not re.search(r"(?m)^name:\s*personal-workbench\s*$", frontmatter):
        raise ValueError("Hermes 技能名称必须为 personal-workbench")
    if not re.search(r"(?m)^description:\s*\S", frontmatter):
        raise ValueError("Hermes 技能缺少 description")
    if re.search(r"wba\.[A-Za-z0-9._-]{12,}", content):
        raise ValueError("Hermes 技能中禁止包含 Agent Token")


def _replace_managed_block(existing: str, block: str) -> str:
    start = existing.find(MANAGED_START)
    end = existing.find(MANAGED_END)
    if start >= 0 and end >= start:
        end += len(MANAGED_END)
        merged = existing[:start].rstrip() + "\n\n" + block + existing[end:]
    else:
        merged = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
    return merged.rstrip() + "\n"


def _assert_child(path: Path, parent: Path) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise RuntimeError(f"拒绝处理技能目录之外的路径：{path}") from exc


def _has_existing_connection(hermes_home: Path) -> bool:
    env_path = hermes_home / ".env"
    config_path = hermes_home / "config.yaml"
    if not env_path.is_file() or not config_path.is_file():
        return False
    token_present = False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key.strip() == "MCP_PERSONAL_WORKBENCH_API_KEY" and value.strip():
            token_present = True
            break
    config_text = config_path.read_text(encoding="utf-8")
    return token_present and "personal_workbench" in config_text and "https://" in config_text


def _configure_image_handoff(hermes_home: Path) -> str:
    os.environ["HERMES_HOME"] = str(hermes_home)
    from hermes_cli.config import load_config, save_config

    config_path = hermes_home / "config.yaml"
    config = load_config()
    agent = config.setdefault("agent", {})
    if not isinstance(agent, dict):
        agent = {}
        config["agent"] = agent
    previous = str(agent.get("image_input_mode") or "auto")
    if previous == "text":
        return previous
    if config_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(config_path, config_path.with_name(f"config.yaml.workbench-media-{stamp}.bak"))
    agent["image_input_mode"] = "text"
    save_config(config)
    return previous


def install_assets(
    *,
    hermes_home: Path,
    source_skill_root: Path,
    operating_rules_path: Path,
    configure_image_handoff: bool = True,
    require_existing_connection: bool = False,
) -> dict[str, object]:
    hermes_home = hermes_home.expanduser().resolve()
    source_skill_root = source_skill_root.resolve()
    operating_rules_path = operating_rules_path.resolve()
    skill_source = source_skill_root / "SKILL.md"
    _validate_skill(skill_source)
    if not operating_rules_path.is_file():
        raise FileNotFoundError(f"缺少工作台规则：{operating_rules_path}")
    if require_existing_connection and not _has_existing_connection(hermes_home):
        raise RuntimeError("没有检测到可复用的 personal_workbench MCP 与专属令牌配置")

    skills_root = (hermes_home / "skills").resolve()
    destination = skills_root / "productivity" / "personal-workbench"
    legacy = skills_root / "software-development" / "personal-workbench-app"
    _assert_child(destination, skills_root)
    _assert_child(legacy, skills_root)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_skill_root, destination)
    references = destination / "references"
    references.mkdir(parents=True, exist_ok=True)
    shutil.copy2(operating_rules_path, references / "operating-rules.md")

    legacy_removed = False
    if legacy.exists():
        shutil.rmtree(legacy)
        legacy_removed = True

    hermes_home.mkdir(parents=True, exist_ok=True)
    soul_path = hermes_home / "SOUL.md"
    existing_soul = soul_path.read_text(encoding="utf-8") if soul_path.is_file() else ""
    soul_path.write_text(_replace_managed_block(existing_soul, MANAGED_SOUL_BLOCK), encoding="utf-8")

    previous_mode = "unchanged"
    if configure_image_handoff:
        previous_mode = _configure_image_handoff(hermes_home)

    return {
        "ok": True,
        "skill_installed": destination.is_dir(),
        "legacy_skill_removed": legacy_removed,
        "soul_managed": MANAGED_START in soul_path.read_text(encoding="utf-8"),
        "image_input_mode": "text" if configure_image_handoff else "unchanged",
        "previous_image_input_mode": previous_mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the persistent Hermes personal-workbench skill.")
    parser.add_argument("--hermes-home", default=os.getenv("HERMES_HOME", ""))
    parser.add_argument("--source-skill-root", required=True)
    parser.add_argument("--operating-rules", required=True)
    parser.add_argument("--skip-image-handoff-config", action="store_true")
    parser.add_argument("--require-existing-connection", action="store_true")
    args = parser.parse_args()

    if args.hermes_home.strip():
        hermes_home = Path(args.hermes_home)
    else:
        try:
            from hermes_cli.config import get_hermes_home

            hermes_home = get_hermes_home()
        except ImportError:
            hermes_home = Path.home() / ".hermes"

    result = install_assets(
        hermes_home=hermes_home,
        source_skill_root=Path(args.source_skill_root),
        operating_rules_path=Path(args.operating_rules),
        configure_image_handoff=not args.skip_image_handoff_config,
        require_existing_connection=args.require_existing_connection,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
