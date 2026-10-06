import json
import os
from pathlib import Path
from typing import Any


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return root()


def public_url() -> str:
    return os.getenv(
        "GATEWAY_PUBLIC_URL", os.getenv("GATEWAY_ISSUER_URL", "http://localhost:8000")
    ).rstrip("/")


def resolve_configured_path(env_name: str, default: str) -> Path:
    raw = os.getenv(env_name, default)
    path = Path(raw)
    if not path.is_absolute():
        cwd_path = (Path.cwd() / path).resolve()
        if cwd_path.exists():
            return cwd_path
        path = (root() / path).resolve()
    return path


def tools_file() -> Path:
    return resolve_configured_path("GATEWAY_TOOLS_FILE", "gateway-tools.json")


def factory_projects_file() -> Path:
    return resolve_configured_path(
        "GATEWAY_FACTORY_PROJECTS_FILE",
        "gateway-factory-projects.json",
    )


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))
