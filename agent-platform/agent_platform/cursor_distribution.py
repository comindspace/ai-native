from __future__ import annotations

import hashlib
import shutil
import zipfile
import os
from pathlib import Path
from typing import Any

from agent_platform.io import read_json, write_json, write_text


DEFAULT_CURSOR_DISTRIBUTION_URL = os.environ.get("GATEWAY_PLUGINS_URL", "https://gateway.example.com/plugins/cursor")
_SKIPPED_PARTS = {"__pycache__", ".DS_Store"}


def _iter_plugin_files(plugin_root: Path) -> list[Path]:
    return [
        path
        for path in sorted(plugin_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
        and not any(part in _SKIPPED_PARTS for part in path.relative_to(plugin_root).parts)
        and path.suffix != ".pyc"
    ]


def _zip_mode(path: Path) -> int:
    if path.suffix in {".sh", ".bash"}:
        return 0o755
    return 0o644


def _write_deterministic_zip(plugin_root: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        for path in _iter_plugin_files(plugin_root):
            relative = path.relative_to(plugin_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (_zip_mode(path) & 0xFFFF) << 16
            info.create_system = 3
            bundle.writestr(info, path.read_bytes(), compresslevel=9)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_cursor_distribution(
    plugins_root: Path,
    output: Path,
    installer_source: Path,
    platform_release: str,
    base_url: str = DEFAULT_CURSOR_DISTRIBUTION_URL,
    clean: bool = False,
) -> dict[str, Any]:
    if clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    plugins: list[dict[str, Any]] = []
    checksum_rows: list[tuple[str, str]] = []
    for plugin_root in sorted(plugins_root.iterdir(), key=lambda path: path.name):
        manifest_path = plugin_root / ".cursor-plugin" / "plugin.json"
        if not plugin_root.is_dir() or not manifest_path.is_file():
            continue

        manifest = read_json(manifest_path)
        name = str(manifest.get("name") or "").strip()
        version = str(manifest.get("version") or "").strip()
        if name != plugin_root.name or not version:
            raise ValueError(f"invalid Cursor plugin manifest: {manifest_path}")

        versioned_filename = f"{name}-{version}.zip"
        current_filename = f"{name}.zip"
        versioned_archive = output / versioned_filename
        current_archive = output / current_filename
        _write_deterministic_zip(plugin_root, versioned_archive)
        shutil.copyfile(versioned_archive, current_archive)

        checksum = _sha256(versioned_archive)
        checksum_rows.extend(
            [(versioned_filename, checksum), (current_filename, checksum)]
        )
        plugins.append(
            {
                "name": name,
                "version": version,
                "filename": current_filename,
                "versionedFilename": versioned_filename,
                "url": f"{base_url.rstrip('/')}/{current_filename}",
                "sha256": checksum,
                "sizeBytes": versioned_archive.stat().st_size,
                "installPath": f"~/.cursor/plugins/local/{name}",
                "manifest": ".cursor-plugin/plugin.json",
            }
        )

    if not plugins:
        raise ValueError(f"no Cursor plugins found in {plugins_root}")

    for installer_name in ("install.sh", "install.ps1"):
        source = installer_source / installer_name
        if not source.is_file():
            raise FileNotFoundError(source)
        target = output / installer_name
        shutil.copyfile(source, target)
        checksum_rows.append((installer_name, _sha256(target)))

    write_json(
        output / "latest.json",
        {
            "schema": 1,
            "platformRelease": platform_release,
            "baseUrl": base_url.rstrip("/"),
            "plugins": plugins,
        },
    )
    write_text(
        output / "SHA256SUMS",
        "".join(
            f"{checksum}  {filename}\n"
            for filename, checksum in sorted(checksum_rows)
        ),
    )
    return {
        "target": "cursor-distribution",
        "path": str(output),
        "plugins": len(plugins),
        "platformRelease": platform_release,
        "baseUrl": base_url.rstrip("/"),
    }
