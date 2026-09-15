from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    directory: str
    path: Path
    description: str
    has_references: bool
    has_reference: bool
    has_scripts: bool
    has_assets: bool
    has_manifest: bool
