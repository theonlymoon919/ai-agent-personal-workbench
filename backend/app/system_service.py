from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


STARTUP_VALUE_NAME = "PersonalWorkbench"


def packaged_executable() -> Path | None:
    configured = os.getenv("WORKBENCH_EXECUTABLE", "").strip()
    if configured:
        candidate = Path(configured).resolve()
        if candidate.is_file():
            return candidate
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def startup_status() -> dict[str, Any]:
    executable = packaged_executable()
    if os.name != "nt" or executable is None:
        return {"available": False, "enabled": False, "label": "正式 Windows 版中可设置"}
    import winreg

    enabled = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            enabled = str(executable).lower() in str(value).lower()
    except FileNotFoundError:
        pass
    return {"available": True, "enabled": enabled, "label": "已开机启动" if enabled else "未开机启动"}


def update_startup(enabled: bool) -> dict[str, Any]:
    executable = packaged_executable()
    if os.name != "nt" or executable is None:
        raise ValueError("当前开发版不能设置开机启动，请使用正式 Windows 版")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            launcher_script = os.getenv("WORKBENCH_LAUNCHER_SCRIPT", "").strip()
            command = f'"{executable}" --background'
            if launcher_script:
                command = f'"{executable}" "{Path(launcher_script).resolve()}" --background'
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass
    return startup_status()


def _tailscale_executable() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def remote_access_status() -> dict[str, Any]:
    executable = _tailscale_executable()
    if executable is None:
        return {
            "installed": False,
            "connected": False,
            "serve_enabled": False,
            "url": "",
            "label": "需要安装 Tailscale",
        }
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        status_result = subprocess.run(
            [executable, "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            check=False,
            creationflags=creation_flags,
        )
        status = json.loads(status_result.stdout or "{}")
        self_status = status.get("Self") or {}
        dns_name = str(self_status.get("DNSName") or "").rstrip(".")
        connected = str(status.get("BackendState") or "").lower() == "running"
        serve_result = subprocess.run(
            [executable, "serve", "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            check=False,
            creationflags=creation_flags,
        )
        serve_payload = json.loads(serve_result.stdout or "{}") if serve_result.returncode == 0 else {}
        serve_enabled = bool(serve_payload)
        return {
            "installed": True,
            "connected": connected,
            "serve_enabled": serve_enabled,
            "url": f"https://{dns_name}" if connected and serve_enabled and dns_name else "",
            "label": "手机安全访问已开启" if connected and serve_enabled else "已安装，等待连接和共享",
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {
            "installed": True,
            "connected": False,
            "serve_enabled": False,
            "url": "",
            "label": "暂时无法读取 Tailscale 状态",
        }


def enable_remote_access() -> dict[str, Any]:
    executable = _tailscale_executable()
    if executable is None:
        raise ValueError("请先安装 Tailscale，并在电脑和手机上登录同一个账号")
    current = remote_access_status()
    if not current.get("connected"):
        raise ValueError("请先打开 Tailscale 并完成登录，再回到工作台开启手机访问")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [executable, "serve", "--bg", "--yes", "http://127.0.0.1:8787"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Tailscale Serve 开启失败").strip()
        raise ValueError(detail[:300])
    return remote_access_status()
