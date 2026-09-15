"""Post-process and validate coMind commercial proposal DOCX files.

Usage:
    python format_kp_docx.py proposal.docx
    python format_kp_docx.py proposal.docx --check

The script enforces the Word invariants that are easy to break when a proposal
is assembled programmatically:

- keep title page, TOC, and the final coMind brand page protected;
- format only content tables between the first Heading 1 and the final brand
  page;
- keep content table text at least 11 pt;
- keep compact table row height and margins;
- keep table headings attached to their tables and mark first rows as
  non-splitting repeatable headers;
- use one row-level white internal vertical border rule in dark table headers;
- detect fragile numbered lists that reuse a Word numbering stream without an
  explicit restart;
- optionally detect forbidden font attributes and explicit font sizes below the
  requested minimum across the whole DOCX package;
- ensure the final "coMind Value-Driven-AI" title is a real Heading 1 that
  starts on a new page.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("lxml is required. Install python-docx or lxml first.") from exc


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = NS["w"]
W_NS = f"{{{W}}}"


def qn(local_name: str) -> str:
    return f"{W_NS}{local_name}"


def text_of(el: etree._Element) -> str:
    return "".join(el.xpath(".//w:t/text()", namespaces=NS)).strip()


def ensure_child(parent: etree._Element, local_name: str, insert_at: int | None = None) -> etree._Element:
    child = parent.find(f"w:{local_name}", namespaces=NS)
    if child is None:
        child = etree.Element(qn(local_name))
        if insert_at is None:
            parent.append(child)
        else:
            parent.insert(insert_at, child)
    return child


def get_or_create_ppr(p: etree._Element) -> etree._Element:
    ppr = p.find("w:pPr", namespaces=NS)
    if ppr is None:
        ppr = etree.Element(qn("pPr"))
        p.insert(0, ppr)
    return ppr


def get_style_id(p: etree._Element) -> str | None:
    ppr = p.find("w:pPr", namespaces=NS)
    if ppr is None:
        return None
    style = ppr.find("w:pStyle", namespaces=NS)
    if style is None:
        return None
    return style.get(qn("val"))


def is_heading_1(p: etree._Element) -> bool:
    style_id = get_style_id(p)
    if style_id in {"1", "Heading1", "heading-1"}:
        return True
    text = text_of(p)
    return bool(text[:3] and text[0].isdigit() and ". " in text[:5])


def find_boundaries(root: etree._Element, about_heading: str) -> tuple[etree._Element, list[etree._Element], int | None, int | None]:
    body = root.find("w:body", namespaces=NS)
    if body is None:
        raise ValueError("word/document.xml has no w:body")

    children = list(body)
    about_idx = None
    first_heading_idx = None

    for idx, child in enumerate(children):
        if child.tag != qn("p"):
            continue
        text = text_of(child)
        if about_idx is None and text.startswith(about_heading):
            about_idx = idx
        if first_heading_idx is None and text and not text.startswith(about_heading) and is_heading_1(child):
            first_heading_idx = idx

    return body, children, first_heading_idx, about_idx


def set_about_heading(body_children: list[etree._Element], about_idx: int | None, about_heading: str) -> None:
    if about_idx is None:
        return
    p = body_children[about_idx]
    if text_of(p).startswith(about_heading):
        ppr = get_or_create_ppr(p)
        pstyle = ppr.find("w:pStyle", namespaces=NS)
        if pstyle is None:
            pstyle = etree.Element(qn("pStyle"))
            ppr.insert(0, pstyle)
        pstyle.set(qn("val"), "1")
        ensure_child(ppr, "pageBreakBefore")


def set_cell_margin(cell: etree._Element, top: int, bottom: int, left: int, right: int) -> None:
    tc_pr = ensure_child(cell, "tcPr", insert_at=0)
    tc_mar = ensure_child(tc_pr, "tcMar")
    for local_name, value in {
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
    }.items():
        node = ensure_child(tc_mar, local_name)
        node.set(qn("w"), str(value))
        node.set(qn("type"), "dxa")


def set_min_font(run: etree._Element, half_points: int) -> None:
    rpr = run.find("w:rPr", namespaces=NS)
    if rpr is None:
        rpr = etree.Element(qn("rPr"))
        run.insert(0, rpr)
    for local_name in ("sz", "szCs"):
        node = rpr.find(f"w:{local_name}", namespaces=NS)
        if node is None:
            node = etree.Element(qn(local_name))
            rpr.append(node)
            current = None
        else:
            raw = node.get(qn("val"))
            current = int(raw) if raw and raw.isdigit() else None
        if current is None or current < half_points:
            node.set(qn("val"), str(half_points))


def ensure_row_flag(row: etree._Element, local_name: str) -> None:
    tr_pr = row.find("w:trPr", namespaces=NS)
    if tr_pr is None:
        tr_pr = etree.Element(qn("trPr"))
        row.insert(0, tr_pr)
    ensure_child(tr_pr, local_name)


def ensure_keep_next(p: etree._Element) -> None:
    ppr = get_or_create_ppr(p)
    ensure_child(ppr, "keepNext")


def set_nil_border(parent: etree._Element, edge: str) -> None:
    border = ensure_child(parent, edge)
    border.set(qn("val"), "nil")
    border.set(qn("sz"), "0")
    border.set(qn("space"), "0")
    border.set(qn("color"), "auto")


def set_white_border(parent: etree._Element, edge: str) -> None:
    border = ensure_child(parent, edge)
    border.set(qn("val"), "single")
    border.set(qn("sz"), "8")
    border.set(qn("space"), "0")
    border.set(qn("color"), "FFFFFF")


def remove_header_cell_vertical_borders(cell: etree._Element) -> None:
    tc_pr = ensure_child(cell, "tcPr", insert_at=0)
    borders = ensure_child(tc_pr, "tcBorders")
    for edge in ("left", "right"):
        existing = borders.find(f"w:{edge}", namespaces=NS)
        if existing is not None:
            borders.remove(existing)


def set_header_row_inside_vertical_border(row: etree._Element) -> None:
    tr_pr = row.find("w:trPr", namespaces=NS)
    if tr_pr is None:
        tr_pr = etree.Element(qn("trPr"))
        row.insert(0, tr_pr)
    tbl_pr_ex = ensure_child(tr_pr, "tblPrEx")
    borders = ensure_child(tbl_pr_ex, "tblBorders")
    set_white_border(borders, "insideV")


def format_content_table(
    table: etree._Element,
    *,
    row_height_twips: int,
    margin_vertical_twips: int,
    margin_horizontal_twips: int,
    min_font_half_points: int,
) -> None:
    rows = table.xpath("./w:tr", namespaces=NS)
    for row_idx, row in enumerate(rows):
        tr_pr = row.find("w:trPr", namespaces=NS)
        if tr_pr is None:
            tr_pr = etree.Element(qn("trPr"))
            row.insert(0, tr_pr)
        tr_height = tr_pr.find("w:trHeight", namespaces=NS)
        if tr_height is None:
            tr_height = etree.Element(qn("trHeight"))
            tr_pr.append(tr_height)
        tr_height.set(qn("val"), str(row_height_twips))
        tr_height.set(qn("hRule"), "atLeast")
        ensure_row_flag(row, "cantSplit")
        if row_idx == 0:
            ensure_row_flag(row, "tblHeader")
            set_header_row_inside_vertical_border(row)

        cells = row.xpath("./w:tc", namespaces=NS)
        for cell_idx, cell in enumerate(cells):
            set_cell_margin(
                cell,
                top=margin_vertical_twips,
                bottom=margin_vertical_twips,
                left=margin_horizontal_twips,
                right=margin_horizontal_twips,
            )
            if row_idx == 0:
                tc_pr = ensure_child(cell, "tcPr", insert_at=0)
                valign = ensure_child(tc_pr, "vAlign")
                valign.set(qn("val"), "center")
                remove_header_cell_vertical_borders(cell)

            for run in cell.xpath(".//w:r[w:t]", namespaces=NS):
                set_min_font(run, min_font_half_points)


def content_tables(children: list[etree._Element], first_heading_idx: int | None, about_idx: int | None) -> list[etree._Element]:
    start = (first_heading_idx + 1) if first_heading_idx is not None else 0
    end = about_idx if about_idx is not None else len(children)
    return [child for child in children[start:end] if child.tag == qn("tbl")]


def content_table_indexes(children: list[etree._Element], first_heading_idx: int | None, about_idx: int | None) -> list[int]:
    start = (first_heading_idx + 1) if first_heading_idx is not None else 0
    end = about_idx if about_idx is not None else len(children)
    return [idx for idx in range(start, end) if children[idx].tag == qn("tbl")]


def table_headers(table: etree._Element) -> list[str]:
    first_row = table.find("w:tr", namespaces=NS)
    if first_row is None:
        return []
    headers = []
    for cell in first_row.xpath("./w:tc", namespaces=NS):
        headers.append(" ".join(text_of(cell).split()))
    return headers


def previous_nonempty_paragraph(children: list[etree._Element], table_idx: int) -> etree._Element | None:
    for idx in range(table_idx - 1, -1, -1):
        child = children[idx]
        if child.tag != qn("p"):
            return None
        if text_of(child):
            return child
    return None


def style_id_of_paragraph(p: etree._Element) -> str | None:
    return get_style_id(p) or ""


def is_heading_style(style_id: str | None) -> bool:
    if not style_id:
        return False
    normalized = style_id.lower()
    return normalized.startswith("heading") or normalized in {"1", "2", "3", "4", "5", "6"}


def paragraph_num_id(p: etree._Element) -> tuple[str | None, str]:
    num_id = p.find("./w:pPr/w:numPr/w:numId", namespaces=NS)
    ilvl = p.find("./w:pPr/w:numPr/w:ilvl", namespaces=NS)
    return (
        num_id.get(qn("val")) if num_id is not None else None,
        ilvl.get(qn("val")) if ilvl is not None else "0",
    )


def parse_numbering(package_dir: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    numbering_xml = package_dir / "word" / "numbering.xml"
    if not numbering_xml.exists():
        return set(), set()

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.parse(str(numbering_xml), parser).getroot()
    abstract_formats: dict[tuple[str, str], str] = {}
    for abstract in root.xpath("./w:abstractNum", namespaces=NS):
        abstract_id = abstract.get(qn("abstractNumId"))
        if abstract_id is None:
            continue
        for lvl in abstract.xpath("./w:lvl", namespaces=NS):
            ilvl = lvl.get(qn("ilvl"), "0")
            num_fmt = lvl.find("./w:numFmt", namespaces=NS)
            if num_fmt is not None:
                abstract_formats[(abstract_id, ilvl)] = num_fmt.get(qn("val"), "")

    decimal_num_levels: set[tuple[str, str]] = set()
    restart_overrides: set[tuple[str, str]] = set()
    for num in root.xpath("./w:num", namespaces=NS):
        num_id = num.get(qn("numId"))
        abstract = num.find("./w:abstractNumId", namespaces=NS)
        abstract_id = abstract.get(qn("val")) if abstract is not None else None
        if num_id is None or abstract_id is None:
            continue
        for (candidate_abstract_id, ilvl), fmt in abstract_formats.items():
            if candidate_abstract_id == abstract_id and fmt == "decimal":
                decimal_num_levels.add((num_id, ilvl))
        for override in num.xpath("./w:lvlOverride", namespaces=NS):
            ilvl = override.get(qn("ilvl"), "0")
            start = override.find("./w:startOverride", namespaces=NS)
            if start is not None and start.get(qn("val")) == "1":
                restart_overrides.add((num_id, ilvl))

    return decimal_num_levels, restart_overrides


def validate_numbering(children: list[etree._Element], package_dir: Path) -> dict[str, list]:
    decimal_num_levels, restart_overrides = parse_numbering(package_dir)
    issues: dict[str, list] = {
        "numbered_list_restart_missing": [],
        "mixed_numbering_modes": [],
    }
    if not decimal_num_levels:
        return {}

    sequences: dict[tuple[str, str], list[dict[str, object]]] = {}
    active_key: tuple[str, str] | None = None
    word_numbered_count = 0
    explicit_numbered_count = 0

    for idx, child in enumerate(children):
        if child.tag != qn("p"):
            active_key = None
            continue

        text = text_of(child)
        style_id = style_id_of_paragraph(child)
        num_id, ilvl = paragraph_num_id(child)
        key = (num_id, ilvl) if num_id is not None else None
        is_decimal_numbered = key in decimal_num_levels if key is not None else False

        if is_decimal_numbered and key is not None:
            word_numbered_count += 1
            if key != active_key:
                sequences.setdefault(key, []).append({"paragraph_index": idx, "text": text[:80]})
            active_key = key
            continue

        if text:
            if re.match(r"^\d+\.\s+", text) and not is_heading_style(style_id):
                explicit_numbered_count += 1
            active_key = None

    for key, starts in sequences.items():
        if len(starts) <= 1 or key in restart_overrides:
            continue
        num_id, ilvl = key
        issues["numbered_list_restart_missing"].append(
            {"numId": num_id, "ilvl": ilvl, "starts": starts[:10], "sequence_count": len(starts)}
        )

    if word_numbered_count and explicit_numbered_count:
        issues["mixed_numbering_modes"].append(
            {"word_numbered_paragraphs": word_numbered_count, "explicit_numbered_paragraphs": explicit_numbered_count}
        )

    return {key: value for key, value in issues.items() if value}


def iter_word_xml(package_dir: Path) -> list[Path]:
    word_dir = package_dir / "word"
    if not word_dir.exists():
        return []
    return sorted(path for path in word_dir.rglob("*.xml") if path.is_file())


def validate_package_fonts(
    package_dir: Path,
    *,
    min_font_half_points: int,
    disallowed_fonts: list[str],
    strict_min_font: bool,
) -> dict[str, list]:
    issues: dict[str, list] = {
        "disallowed_font_attrs": [],
        "explicit_font_below_min": [],
    }
    disallowed = {font.lower() for font in disallowed_fonts}
    if not disallowed and not strict_min_font:
        return {}

    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    for xml_path in iter_word_xml(package_dir):
        rel = xml_path.relative_to(package_dir).as_posix()
        try:
            root = etree.parse(str(xml_path), parser).getroot()
        except etree.XMLSyntaxError:
            continue

        if disallowed:
            for node in root.xpath(".//w:rFonts", namespaces=NS):
                for raw_name, raw_value in node.attrib.items():
                    local_name = etree.QName(raw_name).localname
                    if local_name not in {"ascii", "hAnsi", "eastAsia", "cs"}:
                        continue
                    if raw_value.lower() in disallowed:
                        issues["disallowed_font_attrs"].append(
                            {"file": rel, "attr": local_name, "font": raw_value}
                        )
            for font_node in root.xpath(".//*[local-name()='font']", namespaces=NS):
                raw_value = font_node.get("typeface")
                if raw_value and raw_value.lower() in disallowed:
                    issues["disallowed_font_attrs"].append({"file": rel, "attr": "typeface", "font": raw_value})

        if strict_min_font:
            for node in root.xpath(".//w:sz | .//w:szCs", namespaces=NS):
                raw_value = node.get(qn("val"))
                value = int(raw_value) if raw_value and raw_value.isdigit() else None
                if value is not None and value < min_font_half_points:
                    issues["explicit_font_below_min"].append(
                        {"file": rel, "tag": etree.QName(node).localname, "size_half_points": value}
                    )

    return {key: value for key, value in issues.items() if value}


def validate(
    root: etree._Element,
    *,
    package_dir: Path,
    about_heading: str,
    require_about: bool,
    row_height_twips: int,
    min_font_half_points: int,
    disallowed_fonts: list[str],
    strict_min_font: bool,
) -> dict[str, list]:
    _body, children, first_heading_idx, about_idx = find_boundaries(root, about_heading)
    issues: dict[str, list] = {
        "missing_about_heading": [],
        "about_heading_not_heading_1": [],
        "about_heading_no_page_break": [],
        "content_table_font": [],
        "content_table_row_height": [],
        "content_header_border": [],
        "table_header_repeat_missing": [],
        "table_header_cant_split_missing": [],
        "table_row_cant_split_missing": [],
        "table_preceding_keep_next_missing": [],
        "duplicate_header_columns": [],
        "adjacent_tables_without_separator": [],
    }
    issues.update(validate_numbering(children, package_dir))
    issues.update(
        validate_package_fonts(
            package_dir,
            min_font_half_points=min_font_half_points,
            disallowed_fonts=disallowed_fonts,
            strict_min_font=strict_min_font,
        )
    )

    if require_about and about_idx is None:
        issues["missing_about_heading"].append(about_heading)

    if about_idx is not None:
        about_p = children[about_idx]
        if get_style_id(about_p) not in {"1", "Heading1"}:
            issues["about_heading_not_heading_1"].append(get_style_id(about_p))
        ppr = about_p.find("w:pPr", namespaces=NS)
        if ppr is None or ppr.find("w:pageBreakBefore", namespaces=NS) is None:
            issues["about_heading_no_page_break"].append(about_heading)

    start = (first_heading_idx + 1) if first_heading_idx is not None else 0
    end = about_idx if about_idx is not None else len(children)

    previous_content = None
    for idx in range(start, end):
        child = children[idx]
        if child.tag == qn("p"):
            txt = text_of(child)
            if txt:
                previous_content = "paragraph"
            elif previous_content != "table":
                previous_content = "blank"
            continue
        if child.tag != qn("tbl"):
            continue

        if previous_content == "table":
            issues["adjacent_tables_without_separator"].append(idx)
        previous_content = "table"

        headers = table_headers(child)
        for pos in range(1, len(headers)):
            if headers[pos] and headers[pos] == headers[pos - 1]:
                issues["duplicate_header_columns"].append({"table_index": idx, "header": headers[pos]})

        rows = child.xpath("./w:tr", namespaces=NS)
        for row_idx, row in enumerate(rows):
            tr_pr = row.find("./w:trPr", namespaces=NS)
            if tr_pr is None or tr_pr.find("./w:cantSplit", namespaces=NS) is None:
                issues["table_row_cant_split_missing"].append({"table_index": idx, "row": row_idx})
            if row_idx == 0:
                if tr_pr is None or tr_pr.find("./w:tblHeader", namespaces=NS) is None:
                    issues["table_header_repeat_missing"].append({"table_index": idx})
                if tr_pr is None or tr_pr.find("./w:cantSplit", namespaces=NS) is None:
                    issues["table_header_cant_split_missing"].append({"table_index": idx})
                prev = previous_nonempty_paragraph(children, idx)
                prev_ppr = prev.find("w:pPr", namespaces=NS) if prev is not None else None
                if prev is not None and (prev_ppr is None or prev_ppr.find("w:keepNext", namespaces=NS) is None):
                    issues["table_preceding_keep_next_missing"].append(
                        {"table_index": idx, "previous_text": text_of(prev)[:80]}
                    )

            tr_height = row.find("./w:trPr/w:trHeight", namespaces=NS)
            raw_height = tr_height.get(qn("val")) if tr_height is not None else None
            height = int(raw_height) if raw_height and raw_height.isdigit() else 0
            if height < row_height_twips:
                issues["content_table_row_height"].append({"table_index": idx, "row": row_idx, "height": height})

            cells = row.xpath("./w:tc", namespaces=NS)
            for cell_idx, cell in enumerate(cells):
                if row_idx == 0:
                    if row_idx == 0 and cell_idx == 0:
                        inside_v = row.find("./w:trPr/w:tblPrEx/w:tblBorders/w:insideV", namespaces=NS)
                        if (
                            inside_v is None
                            or inside_v.get(qn("val")) != "single"
                            or inside_v.get(qn("color")) != "FFFFFF"
                        ):
                            issues["content_header_border"].append(
                                {"table_index": idx, "cell": cell_idx, "edge": "row-insideV"}
                            )
                    for edge in ("left", "right"):
                        border = cell.find(f"./w:tcPr/w:tcBorders/w:{edge}", namespaces=NS)
                        if border is not None:
                            issues["content_header_border"].append({"table_index": idx, "cell": cell_idx, "edge": edge})

                for run in cell.xpath(".//w:r[w:t]", namespaces=NS):
                    txt = text_of(run)
                    if not txt:
                        continue
                    sz = run.find("./w:rPr/w:sz", namespaces=NS)
                    raw = sz.get(qn("val")) if sz is not None else None
                    value = int(raw) if raw and raw.isdigit() else 0
                    if value < min_font_half_points:
                        issues["content_table_font"].append(
                            {"table_index": idx, "row": row_idx, "cell": cell_idx, "size": value, "text": txt[:40]}
                        )

    return {key: value for key, value in issues.items() if value}


def process_docx(path: Path, args: argparse.Namespace) -> dict[str, list]:
    min_font_half_points = int(round(args.min_font_pt * 2))

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        with ZipFile(path, "r") as zin:
            zin.extractall(tmp)

        document_xml = tmp / "word" / "document.xml"
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(document_xml), parser)
        root = tree.getroot()
        _body, children, first_heading_idx, about_idx = find_boundaries(root, args.about_heading)

        if not args.check:
            set_about_heading(children, about_idx, args.about_heading)
            for table_idx in content_table_indexes(children, first_heading_idx, about_idx):
                table = children[table_idx]
                prev = previous_nonempty_paragraph(children, table_idx)
                if prev is not None:
                    ensure_keep_next(prev)
                format_content_table(
                    table,
                    row_height_twips=args.row_height_twips,
                    margin_vertical_twips=args.margin_vertical_twips,
                    margin_horizontal_twips=args.margin_horizontal_twips,
                    min_font_half_points=min_font_half_points,
                )
            tree.write(str(document_xml), encoding="UTF-8", xml_declaration=True, standalone=True)

        issues = validate(
            root,
            package_dir=tmp,
            about_heading=args.about_heading,
            require_about=not args.allow_missing_about,
            row_height_twips=args.row_height_twips,
            min_font_half_points=min_font_half_points,
            disallowed_fonts=args.disallow_font,
            strict_min_font=args.strict_min_font,
        )

        if not args.check:
            out = path.with_suffix(path.suffix + ".tmp")
            if out.exists():
                out.unlink()
            with ZipFile(out, "w", ZIP_DEFLATED) as zout:
                for file_path in tmp.rglob("*"):
                    if file_path.is_file():
                        zout.write(file_path, file_path.relative_to(tmp).as_posix())
            shutil.move(str(out), str(path))

    return issues


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path, help="Path to a .docx file")
    parser.add_argument("--check", action="store_true", help="Validate only; do not modify the file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable validation output")
    parser.add_argument("--about-heading", default="coMind Value-Driven-AI")
    parser.add_argument("--allow-missing-about", action="store_true", help="Do not fail if the final coMind page is absent")
    parser.add_argument("--min-font-pt", type=float, default=11.0)
    parser.add_argument(
        "--strict-min-font",
        action="store_true",
        help="Fail if any explicit w:sz/w:szCs in the DOCX package is below --min-font-pt",
    )
    parser.add_argument(
        "--disallow-font",
        action="append",
        default=[],
        help="Fail if this font appears in DOCX font attributes; repeat for multiple fonts",
    )
    parser.add_argument("--row-height-twips", type=int, default=587)
    parser.add_argument("--margin-vertical-twips", type=int, default=120)
    parser.add_argument("--margin-horizontal-twips", type=int, default=80)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    path = args.docx.resolve()
    if not path.exists():
        print(f"Error: not found: {path}", file=sys.stderr)
        return 2
    if path.suffix.lower() != ".docx":
        print(f"Error: expected a .docx file: {path}", file=sys.stderr)
        return 2

    issues = process_docx(path, args)
    result = {"ok": not issues, "path": str(path), "issues": issues}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif issues:
        print(f"DOCX validation failed: {path}")
        for key, value in issues.items():
            print(f"- {key}: {len(value)}")
    else:
        action = "validated" if args.check else "formatted and validated"
        print(f"DOCX {action}: {path}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
