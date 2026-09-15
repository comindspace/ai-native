from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    """Write text with LF line endings regardless of platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value


def _parse_scalar(value: str) -> str:
    value = _strip_inline_comment(value.strip())
    if not value:
        return ""

    if value[0] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise ValueError("unterminated quoted scalar")
        if quote == '"':
            return json.loads(value)
        return value[1:-1].replace("''", "'")

    if ": " in value:
        raise ValueError("plain scalar contains ': '; quote the value or use a block scalar")
    if value.startswith(("[", "{", "-", "&", "*", "!", "@", "`")):
        raise ValueError("unsupported YAML scalar syntax")
    return value


def _parse_nested_block(lines: list[str], start: int) -> tuple[str, int]:
    values: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if not line.startswith((" ", "\t")):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            _parse_scalar(stripped[2:])
        else:
            if ":" not in stripped:
                raise ValueError(f"expected nested 'key: value' on line {index + 1}")
            key, value = stripped.split(":", 1)
            if not key.strip():
                raise ValueError(f"empty nested key on line {index + 1}")
            if value.strip():
                _parse_scalar(value)
        values.append(stripped)
        index += 1
    return "\n".join(values), index


def _parse_block_scalar(lines: list[str], start: int, folded: bool) -> tuple[str, int]:
    parts: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line and not line[0].isspace():
            break
        stripped = line.strip()
        if stripped:
            parts.append(stripped)
        index += 1
    separator = " " if folded else "\n"
    return separator.join(parts), index


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}

    frontmatter = text[3:end].strip("\r\n")
    if not frontmatter:
        return {}

    lines = frontmatter.splitlines()
    result: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if line.startswith((" ", "\t")):
            raise ValueError(f"unexpected indentation on line {index + 1}")
        if ":" not in line:
            raise ValueError(f"expected 'key: value' on line {index + 1}")

        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty key on line {index + 1}")
        if any(char.isspace() for char in key):
            raise ValueError(f"invalid key on line {index + 1}: {key}")

        value = value.strip()
        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            result[key], index = _parse_block_scalar(lines, index + 1, value.startswith(">"))
            continue
        if not value and index + 1 < len(lines) and lines[index + 1].startswith((" ", "\t")):
            result[key], index = _parse_nested_block(lines, index + 1)
            continue

        result[key] = _parse_scalar(value)
        index += 1
    return result
