"""Open the bundled Windows updater from a local tool UI."""

from pathlib import Path
import json
import os
import re
import subprocess


def _command(root: Path, action: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-STA", "-File", str(root / "Standalone-Update.ps1"), "-Action", action]


def check_update(root: Path) -> dict:
    if os.name != "nt" or not (root / "Standalone-Update.ps1").is_file():
        return {"ok": False}
    try:
        result = subprocess.run(
            _command(root, "Check"), capture_output=True, check=True,
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"ok": False}


def open_update(root: Path, version: str | None = None) -> dict:
    script = root / "Standalone-Update.ps1"
    if os.name != "nt" or not script.is_file():
        return {"ok": False, "error": {"message": "找不到獨立更新程式。"}}
    try:
        arguments = _command(root, "Show")
        if version is not None:
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                return {"ok": False, "error": {"message": "更新版號格式不正確。"}}
            arguments.extend(["-Version", version])
        subprocess.Popen(
            arguments,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as exc:
        return {"ok": False, "error": {"message": str(exc)}}
    return {"ok": True}


def handle_update(root: Path, body: dict) -> dict:
    if isinstance(body, dict):
        if body.get("action") == "check":
            return check_update(root)
        if body.get("action") == "open" and body.get("version"):
            return open_update(root, body["version"])
    return {"ok": False, "error": {"message": "更新請求格式不正確。"}}
