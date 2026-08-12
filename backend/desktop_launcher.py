from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


if not getattr(sys, "frozen", False):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


APP_NAME = "AI Agent 个人工作台"
HOST = "127.0.0.1"
PORT = 8787
URL = f"http://{HOST}:{PORT}/"


def runtime_root() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "PersonalWorkbench"


def documents_root() -> Path:
    return Path.home() / "Documents"


def parse_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def choose_data_directory() -> Path:
    default = documents_root() / "个人工作台数据"
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(
            APP_NAME,
            "第一次启动需要选择个人数据文件夹。\n\n"
            "如果你已经使用 Obsidian，请选择原来的“个人工作台”文件夹；"
            "也可以取消选择，让软件自动建立独立数据文件夹。",
            parent=root,
        )
        chosen = filedialog.askdirectory(
            title="选择个人工作台数据文件夹",
            initialdir=str(default.parent if default.parent.exists() else Path.home()),
            mustexist=False,
            parent=root,
        )
        root.destroy()
        return Path(chosen) if chosen else default
    except Exception:
        return default


def write_private_hermes_guide(root: Path, token: str) -> None:
    guide = root / "Agent接入说明.txt"
    guide.write_text(
        "AI Agent 个人工作台 · 本机接入信息\n"
        "================================\n\n"
        "请让本机 AI Agent 添加一个名为 personal_workbench 的 MCP 服务：\n\n"
        f"URL: http://127.0.0.1:{PORT}/mcp/\n"
        f"Authorization: Bearer {token}\n"
        "Transport: streamable HTTP\n"
        "Timeout: 180 秒\n\n"
        "连接后，先调用 get_dashboard 和 get_workbench_preferences 了解工作台。\n"
        "这是本机私密连接信息，请不要上传或转发。\n",
        encoding="utf-8",
    )


def ensure_config(background: bool) -> tuple[Path, dict[str, str]]:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.env"
    values = parse_config(config_path)
    if not values.get("WORKBENCH_PATH"):
        data_path = documents_root() / "个人工作台数据" if background else choose_data_directory()
        values = {
            "WORKBENCH_MCP_TOKEN": f"wb_{secrets.token_hex(32)}",
            "WORKBENCH_PATH": str(data_path.resolve()),
            "CACHE_PATH": str((root / "cache").resolve()),
            "BACKUP_PATH": str((documents_root() / "个人工作台备份").resolve()),
            "DEFAULT_WATER_TARGET_ML": "2000",
        }
        config_path.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            encoding="utf-8",
        )
    token = values.get("WORKBENCH_MCP_TOKEN") or f"wb_{secrets.token_hex(32)}"
    if values.get("WORKBENCH_MCP_TOKEN") != token:
        values["WORKBENCH_MCP_TOKEN"] = token
        config_path.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            encoding="utf-8",
        )
    write_private_hermes_guide(root, token)
    return root, values


def apply_config(values: dict[str, str]) -> None:
    for key, value in values.items():
        os.environ[key] = value
    os.environ["WORKBENCH_EXECUTABLE"] = str(Path(sys.executable).resolve())
    os.environ["WORKBENCH_LAUNCHER_SCRIPT"] = str(Path(__file__).resolve())
    os.environ["WORKBENCH_INSTALLED"] = "true"
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        os.environ["STATIC_DIR"] = str(bundle_root / "frontend" / "dist")


def workbench_is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}api/health", timeout=1.5) as response:
            return response.status == 200 and b'"ok":true' in response.read().replace(b" ", b"")
    except (OSError, urllib.error.URLError):
        return False


def port_is_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror(APP_NAME, message, parent=root)
        root.destroy()
    except Exception:
        pass


def append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message.rstrip()}\n")
    except OSError:
        pass


def create_tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (25, 71, 55, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((7, 7, 57, 57), radius=15, fill=(246, 244, 236, 255))
    draw.ellipse((20, 16, 44, 40), fill=(77, 126, 96, 255))
    draw.rounded_rectangle((17, 37, 47, 48), radius=5, fill=(193, 146, 61, 255))
    return image


def run_tray(server, server_thread: threading.Thread, runtime: Path) -> None:
    import pystray

    def open_workbench(_icon=None, _item=None) -> None:
        webbrowser.open(URL)

    def open_data(_icon=None, _item=None) -> None:
        data_path = Path(os.environ["WORKBENCH_PATH"])
        data_path.mkdir(parents=True, exist_ok=True)
        os.startfile(data_path)  # type: ignore[attr-defined]

    def open_runtime(_icon=None, _item=None) -> None:
        os.startfile(runtime)  # type: ignore[attr-defined]

    def exit_application(icon, _item=None) -> None:
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "personal-workbench",
        create_tray_image(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem("打开工作台", open_workbench, default=True),
            pystray.MenuItem("打开个人数据文件夹", open_data),
            pystray.MenuItem("打开连接配置文件夹", open_runtime),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出工作台服务", exit_application),
        ),
    )

    def monitor() -> None:
        server_thread.join()
        icon.stop()

    threading.Thread(target=monitor, daemon=True).start()
    icon.run()


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true")
    args, _ = parser.parse_known_args()

    if workbench_is_running():
        if not args.background:
            webbrowser.open(URL)
        return 0
    if port_is_busy():
        show_error(f"端口 {PORT} 正被其他程序使用，AI Agent 个人工作台无法启动。")
        return 1

    runtime, values = ensure_config(args.background)
    apply_config(values)
    log_path = runtime / "workbench.log"
    if sys.stdout is None:
        sys.stdout = log_path.open("a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = log_path.open("a", encoding="utf-8", buffering=1)
    append_log(log_path, "Starting AI Agent Personal Workbench 0.2.0")

    import uvicorn
    from backend.app.main import app

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_errors: list[str] = []

    def run_server() -> None:
        try:
            server.run()
        except BaseException:
            detail = traceback.format_exc()
            server_errors.append(detail)
            append_log(log_path, detail)

    server_thread = threading.Thread(target=run_server, name="workbench-server", daemon=False)
    server_thread.start()

    for _ in range(80):
        if workbench_is_running():
            if not args.background:
                webbrowser.open(URL)
            run_tray(server, server_thread, runtime)
            server_thread.join(timeout=8)
            return 0
        if not server_thread.is_alive():
            break
        time.sleep(0.25)

    server.should_exit = True
    detail = server_errors[-1] if server_errors else "Server did not become ready before the startup deadline."
    append_log(log_path, detail)
    if not args.background:
        show_error("AI Agent 个人工作台启动失败。请打开连接配置文件夹，把 workbench.log 交给开发者检查。")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        emergency_log = runtime_root() / "workbench.log"
        append_log(emergency_log, traceback.format_exc())
        show_error("AI Agent 个人工作台启动失败。请把连接配置文件夹里的 workbench.log 交给开发者检查。")
        raise
