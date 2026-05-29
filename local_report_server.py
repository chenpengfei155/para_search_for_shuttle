#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from gen_html import render_html_rows
from result_dedup import record_key


SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "results" / "local_test"
JSONL_PATH = REPORT_DIR / "test_runs.jsonl"
HTML_PATH = REPORT_DIR / "test_runs.html"
DELETE_API_PATH = "/api/local-test/delete"


def normalize_delete_key(item: list) -> tuple | None:
    if not isinstance(item, list):
        return None
    if len(item) == 6:
        n, q, ell, m, sigma, alpha_h = item
        return (n, q, ell, m, sigma, sigma, alpha_h)
    if len(item) == 7:
        return tuple(item)
    return None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rebuild_report(rows: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(JSONL_PATH, rows)
    render_html_rows(rows, HTML_PATH, delete_api_url=DELETE_API_PATH, collapse_plateaus=False)


class LocalReportHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self) -> None:
        if urlparse(self.path).path != DELETE_API_PATH:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
            return

        keys = payload.get("keys")
        if not isinstance(keys, list):
            self.send_error(HTTPStatus.BAD_REQUEST, "missing keys list")
            return

        delete_keys = {
            normalized
            for item in keys
            if (normalized := normalize_delete_key(item)) is not None
        }

        rows = load_jsonl(JSONL_PATH)
        kept_rows: list[dict] = []
        removed = 0
        for row in rows:
            if record_key(row) in delete_keys:
                removed += 1
                continue
            kept_rows.append(row)

        if removed > 0:
            rebuild_report(kept_rows)

        body = json.dumps({"removed": removed, "remaining": len(kept_rows)}, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve local test report with delete API.")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if JSONL_PATH.exists() and not HTML_PATH.exists():
        rebuild_report(load_jsonl(JSONL_PATH))

    handler = partial(LocalReportHandler)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())