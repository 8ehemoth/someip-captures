#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
grep -E '"event": "(server_start|pid_written|server_exit|stop_by_user)"' oracle_events.events.jsonl | tail -n "${1:-50}"
