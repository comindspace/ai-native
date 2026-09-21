from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_PATHS = [
    Path("plugins"),
    Path(".agents/plugins"),
    Path(".claude-plugin"),
    Path(".cursor-plugin"),
    Path(".zcode-plugin"),
]
GATEWAY_MCP_PUBLIC_URL = os.environ.get("GATEWAY_MCP_PUBLIC_URL", "https://gateway.example.com/mcp")
GATEWAY_MCP_LOGIN_URL = os.environ.get("GATEWAY_MCP_LOGIN_URL", "https://gateway.example.com/auth/yandex/login")


def repo_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()
