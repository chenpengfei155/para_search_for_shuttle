#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import os
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from para_alg_impl import ParameterValidationError, compute_parameters


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MAIN = "{" + MAIN_NS + "}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
XR = "{http://schemas.microsoft.com/office/spreadsheetml/2014/revision}"
X14AC = "{http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac}"
NS = {"main": MAIN_NS}

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")


INPUT_HEADERS = ["n", "q", "ell", "m", "sigma_1", "sigma_2", "alpha_h", "alpha_b"]
OUTPUT_HEADERS = [
    "sigma_b",
    "LWE_security_bit",
    "SIS_UF_security_bit",
    "SIS_sUF_security_bit",
    "PkBytes",
    "SignBytes",
    "CombinedBytes",
    "bk",
    "alpha_1",
    "alpha_s",
    "alpha_e",
    "r",
    "mu_s",
    "v_s",
    "bs",
    "bv",
    "sigma_h",
    "a_h",
    "hh",
]
ERROR_HEADER = "validation_error"


@dataclass(frozen=True)
class RowTask:
    sheet_name: str
    sheet_path: str
    row_number: int
    params: tuple[int, int, int, int, float, float, int, int]


def col_to_index(col: str) -> int:
    value = 0
    for char in col:
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def index_to_col(index: int) -> str:
    chars: list[str] = []
    while index:
        index, rem = divmod(index - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def split_cell_ref(ref: str) -> tuple[str, int]:
    col = "".join(ch for ch in ref if ch.isalpha())
    row = int("".join(ch for ch in ref if ch.isdigit()))
    return col, row


def parse_number(value: str | None) -> int | float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def load_shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall("main:si", NS):
        values.append("".join((t.text or "") for t in si.iter(MAIN + "t")))
    return values


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    typ = cell.attrib.get("t")
    value = cell.find("main:v", NS)
    if typ == "s" and value is not None:
        return shared_strings[int(value.text or "0")]
    if typ == "inlineStr":
        inline = cell.find("main:is", NS)
        if inline is None:
            return ""
        return "".join((t.text or "") for t in inline.iter(MAIN + "t"))
    if value is None:
        formula = cell.find("main:f", NS)
        return "=" + (formula.text or "") if formula is not None else None
    return value.text


def worksheet_paths(zf: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.find("main:sheets", NS):
        name = sheet.attrib["name"]
        rid = sheet.attrib[REL + "id"]
        target = rid_to_target[rid]
        normalized_target = target.lstrip("/")
        sheet_path = normalized_target if normalized_target.startswith("xl/") else "xl/" + normalized_target
        sheets.append((name, sheet_path))
    return sheets


def row_cells(row: ET.Element) -> dict[str, ET.Element]:
    return {cell.attrib["r"]: cell for cell in row.findall("main:c", NS)}


def read_header(row: ET.Element, shared_strings: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for cell in row.findall("main:c", NS):
        col, _ = split_cell_ref(cell.attrib["r"])
        value = cell_value(cell, shared_strings)
        if value:
            headers[value] = col
    return headers


def collect_tasks(xlsx_path: Path) -> tuple[list[RowTask], dict[str, ET.Element], list[tuple[str, str]]]:
    tasks: list[RowTask] = []
    sheet_roots: dict[str, ET.Element] = {}

    with ZipFile(xlsx_path) as zf:
        shared_strings = load_shared_strings(zf)
        sheets = worksheet_paths(zf)

        for sheet_name, sheet_path in sheets:
            root = ET.fromstring(zf.read(sheet_path))
            sheet_roots[sheet_path] = root
            sheet_data = root.find("main:sheetData", NS)
            rows = sheet_data.findall("main:row", NS)
            if not rows:
                continue
            headers = read_header(rows[0], shared_strings)
            missing = [name for name in INPUT_HEADERS + OUTPUT_HEADERS if name not in headers]
            if missing:
                raise RuntimeError(f"{sheet_name} missing headers: {', '.join(missing)}")

            for row in rows[1:]:
                row_number = int(row.attrib["r"])
                cells = row_cells(row)
                values: dict[str, int | float] = {}
                complete = True
                for header in INPUT_HEADERS:
                    col = headers[header]
                    raw = cell_value(cells.get(f"{col}{row_number}"), shared_strings) if f"{col}{row_number}" in cells else None
                    parsed = parse_number(raw)
                    if parsed is None:
                        complete = False
                        break
                    values[header] = parsed
                if not complete:
                    continue

                params = (
                    int(values["n"]),
                    int(values["q"]),
                    int(values["ell"]),
                    int(values["m"]),
                    float(values["sigma_1"]),
                    float(values["sigma_2"]),
                    int(values["alpha_h"]),
                    int(values["alpha_b"]),
                )
                tasks.append(RowTask(sheet_name, sheet_path, row_number, params))

    return tasks, sheet_roots, sheets


def finite_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def compute_one(
    params: tuple[int, int, int, int, float, float, int, int],
) -> tuple[
    tuple[int, int, int, int, float, float, int, int],
    dict[str, float | int | None],
    str | None,
]:
    n, q, ell, m, sigma_1, sigma_2, alpha_h, alpha_b = params
    try:
        result = compute_parameters(n, q, ell, m, sigma_1, sigma_2, alpha_h, alpha_b).result
    except ParameterValidationError as exc:
        return params, {header: None for header in OUTPUT_HEADERS}, str(exc)

    values: dict[str, float | int | None] = {
        "sigma_b": result.sigma_b,
        "LWE_security_bit": finite_number(result.lwe_security_bit),
        "SIS_UF_security_bit": finite_number(result.sis_uf_security_bit),
        "SIS_sUF_security_bit": finite_number(result.sis_suf_security_bit),
        "PkBytes": result.pk_bytes,
        "SignBytes": result.sign_bytes,
        "CombinedBytes": result.combined_bytes,
        "bk": result.bk,
        "alpha_1": result.alpha_1,
        "alpha_s": result.alpha_s,
        "alpha_e": result.alpha_e,
        "r": result.r,
        "mu_s": result.mu_s,
        "v_s": result.v_s,
        "bs": result.bs,
        "bv": result.bv,
        "sigma_h": result.sigma_h,
        "a_h": result.a_h,
        "hh": result.hh,
    }
    return params, values, None


def update_numeric_cell(row: ET.Element, col: str, row_number: int, value: float | int | None) -> None:
    ref = f"{col}{row_number}"
    cells = row.findall("main:c", NS)
    cell = next((candidate for candidate in cells if candidate.attrib.get("r") == ref), None)
    if cell is None:
        cell = ET.Element(MAIN + "c", {"r": ref})
        target_index = col_to_index(col)
        inserted = False
        for idx, existing in enumerate(cells):
            existing_col, _ = split_cell_ref(existing.attrib["r"])
            if col_to_index(existing_col) > target_index:
                row.insert(idx, cell)
                inserted = True
                break
        if not inserted:
            row.append(cell)

    for child_name in ("f", "is"):
        child = cell.find("main:" + child_name, NS)
        if child is not None:
            cell.remove(child)
    cell.attrib.pop("t", None)

    value_node = cell.find("main:v", NS)
    if value is None:
        if value_node is not None:
            cell.remove(value_node)
        return
    if value_node is None:
        value_node = ET.SubElement(cell, MAIN + "v")
    value_node.text = str(value)


def update_text_cell(row: ET.Element, col: str, row_number: int, value: str | None) -> None:
    ref = f"{col}{row_number}"
    cells = row.findall("main:c", NS)
    cell = next((candidate for candidate in cells if candidate.attrib.get("r") == ref), None)
    if cell is None:
        cell = ET.Element(MAIN + "c", {"r": ref})
        target_index = col_to_index(col)
        inserted = False
        for idx, existing in enumerate(cells):
            existing_col, _ = split_cell_ref(existing.attrib["r"])
            if col_to_index(existing_col) > target_index:
                row.insert(idx, cell)
                inserted = True
                break
        if not inserted:
            row.append(cell)

    for child in list(cell):
        cell.remove(child)
    if value is None:
        cell.attrib.pop("t", None)
        return

    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, MAIN + "is")
    text = ET.SubElement(inline, MAIN + "t")
    text.text = value


def update_sheet(
    root: ET.Element,
    output_by_row: dict[int, tuple[dict[str, float | int | None], str | None]],
    shared_strings: list[str],
) -> None:
    sheet_data = root.find("main:sheetData", NS)
    rows = sheet_data.findall("main:row", NS)
    if not rows:
        return
    headers = read_header(rows[0], shared_strings)
    if ERROR_HEADER not in headers:
        headers[ERROR_HEADER] = "AC"
        update_text_cell(rows[0], "AC", 1, ERROR_HEADER)
    rows_by_number = {int(row.attrib["r"]): row for row in rows}

    for row_number, (values, error) in output_by_row.items():
        row = rows_by_number[row_number]
        for header in OUTPUT_HEADERS:
            update_numeric_cell(row, headers[header], row_number, values[header])
        update_text_cell(row, headers[ERROR_HEADER], row_number, error)

    dimension = root.find("main:dimension", NS)
    if dimension is not None:
        max_row = max(rows_by_number)
        dimension.attrib["ref"] = f"A1:AC{max_row}"


def write_workbook(xlsx_path: Path, sheet_roots: dict[str, ET.Element]) -> None:
    original_mode = xlsx_path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(suffix=".xlsx", dir=str(xlsx_path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with ZipFile(xlsx_path, "r") as src, ZipFile(temp_path, "w", ZIP_DEFLATED) as dst:
            modified_paths = set(sheet_roots)
            for item in src.infolist():
                if item.filename in modified_paths:
                    continue
                dst.writestr(item, src.read(item.filename))
            for sheet_path, root in sheet_roots.items():
                # ElementTree drops unused namespace declarations but leaves
                # their prefixes in mc:Ignorable, which makes Excel repair the file.
                root.attrib.pop(MC + "Ignorable", None)
                root.attrib.pop(XR + "uid", None)
                sheet_format = root.find("main:sheetFormatPr", NS)
                if sheet_format is not None:
                    sheet_format.attrib.pop(X14AC + "dyDescent", None)
                xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                dst.writestr(sheet_path, xml)
        shutil.move(str(temp_path), xlsx_path)
        xlsx_path.chmod(original_mode)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Update six_screenshot_parameter_results.xlsx with para_alg_impl.py results.")
    parser.add_argument("--xlsx", type=Path, default=Path("six_screenshot_parameter_results.xlsx"))
    parser.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 1))
    args = parser.parse_args()

    tasks, sheet_roots, sheets = collect_tasks(args.xlsx)
    unique_params = sorted({task.params for task in tasks})
    workers = max(1, min(args.workers, os.cpu_count() or 1))
    print(f"rows={len(tasks)} unique_parameter_sets={len(unique_params)} workers={workers}")

    computed: dict[
        tuple[int, int, int, int, float, float, int, int],
        tuple[dict[str, float | int | None], str | None],
    ] = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(compute_one, params): params for params in unique_params}
        done = 0
        for future in as_completed(futures):
            params, values, error = future.result()
            computed[params] = (values, error)
            done += 1
            status = f"invalid: {error}" if error else "ok"
            print(f"computed {done}/{len(unique_params)}: {params} [{status}]", flush=True)

    output_by_sheet: dict[
        str,
        dict[int, tuple[dict[str, float | int | None], str | None]],
    ] = {}
    for task in tasks:
        output_by_sheet.setdefault(task.sheet_path, {})[task.row_number] = computed[task.params]

    with ZipFile(args.xlsx) as zf:
        shared_strings = load_shared_strings(zf)
    for _, sheet_path in sheets:
        if sheet_path in output_by_sheet:
            update_sheet(sheet_roots[sheet_path], output_by_sheet[sheet_path], shared_strings)

    write_workbook(args.xlsx, sheet_roots)
    print(f"updated {args.xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
