#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$BASE_DIR/.." && pwd)"

SERVER_HOST="${SERVER_HOST:-192.168.40.134}"
SERVER_USER="${SERVER_USER:-server}"
DELAY="${DELAY:-0.5}"

echo "[repro] SERVER_HOST=$SERVER_HOST SERVER_USER=$SERVER_USER DELAY=$DELAY"
echo "[repro] cases dir: $BASE_DIR/repro_cases"
echo

mkdir -p "$BASE_DIR/repro_logs"

for f in "$BASE_DIR"/repro_cases/idx_*.jsonl; do
  idx="$(basename "$f" .jsonl | cut -d_ -f2)"
  echo "=== REPRO idx=$idx file=$f ==="
  python3 "$ROOT/run_testcases.py" \
    --jsonl "$f" \
    --use_run_client_wrapper \
    --oracle callstatus \
    --server_host "$SERVER_HOST" \
    --server_user "$SERVER_USER" \
    --log "$BASE_DIR/repro_logs/repro_${idx}.jsonl" \
    --delay "$DELAY"
done

echo "[repro] done"
