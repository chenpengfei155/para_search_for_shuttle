#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${WEBPAGE_PORT:-8765}"
HTML_REL_PATH="results/local_test/test_runs.html"
PID_FILE="$SCRIPT_DIR/.local_report_server.pid"
LOG_FILE="$SCRIPT_DIR/.local_report_server.log"
SERVER_SCRIPT="$SCRIPT_DIR/local_report_server.py"
LEGACY_PID_FILE="$SCRIPT_DIR/.webpage_server.pid"

primary_ip() {
	hostname -I 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i != "127.0.0.1") { print $i; exit }}'
}

api_ready() {
	"$PYTHON_BIN" - <<PY >/dev/null 2>&1
import json
import urllib.request

url = "http://127.0.0.1:${PORT}/api/local-test/delete"
req = urllib.request.Request(
	url,
	data=json.dumps({"keys": []}).encode("utf-8"),
	headers={"Content-Type": "application/json"},
	method="POST",
)
with urllib.request.urlopen(req, timeout=1) as response:
	raise SystemExit(0 if response.status == 200 else 1)
PY
}

stop_pid_file_process() {
	local pid_file="$1"
	if [[ ! -f "$pid_file" ]]; then
		return
	fi
	local existing_pid
	existing_pid="$(cat "$pid_file")"
	if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
		kill "$existing_pid" 2>/dev/null || true
	fi
	rm -f "$pid_file"
}

ensure_server() {
	if api_ready; then
		return
	fi

	stop_pid_file_process "$LEGACY_PID_FILE"

	if [[ -f "$PID_FILE" ]]; then
		local existing_pid
		existing_pid="$(cat "$PID_FILE")"
		if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
			kill "$existing_pid" 2>/dev/null || true
		fi
		rm -f "$PID_FILE"
	fi

	(
		cd "$SCRIPT_DIR"
		exec "$PYTHON_BIN" "$SERVER_SCRIPT" --port "$PORT" >"$LOG_FILE" 2>&1
	) &
	echo "$!" > "$PID_FILE"

	for _ in {1..20}; do
		if api_ready; then
			return
		fi
		sleep 0.2
	done

	echo "Failed to start local report server on port $PORT" >&2
	echo "See log: $LOG_FILE" >&2
	exit 1
}

cd "$SCRIPT_DIR"
"$PYTHON_BIN" test.py "$@" >/dev/null
ensure_server

HOST="${WEBPAGE_HOST:-$(primary_ip)}"
if [[ -z "$HOST" ]]; then
	HOST="127.0.0.1"
fi

echo "http://$HOST:$PORT/$HTML_REL_PATH"