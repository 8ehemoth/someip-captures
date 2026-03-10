#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

OUT_LOCAL="${OUT_LOCAL:-$BASE_DIR/client_heartbeat.jsonl}"

MERGE_TO_SERVER="${MERGE_TO_SERVER:-1}"
SERVER_HOST="${SERVER_HOST:-server@192.168.40.134}"
SERVER_EVENTS="${SERVER_EVENTS:-/home/server/someip-captures/server/test-someip-service/oracle_events.events.jsonl}"

TIMEOUT_SEC="${TIMEOUT_SEC:-2}"
INTERVAL_SEC="${INTERVAL_SEC:-3}"
FAIL_N="${FAIL_N:-5}"
PING_TIMEOUT_MS="${PING_TIMEOUT_MS:-1000}"

SEND_OK_TO_SERVER="${SEND_OK_TO_SERVER:-0}"
OK_SERVER_EVERY_SEC="${OK_SERVER_EVERY_SEC:-300}"
OK_LOCAL_EVERY_SEC="${OK_LOCAL_EVERY_SEC:-60}"

fail=0
last_ok_send=0
last_ok_local=0

append_local() { echo "$1" >> "$OUT_LOCAL"; }

append_server() {
  local line="$1"
  [[ "$MERGE_TO_SERVER" == "1" ]] || return 0
  ssh -o BatchMode=yes -o ConnectTimeout=2 "$SERVER_HOST" "cat >> '$SERVER_EVENTS'" <<< "$line" >/dev/null 2>&1
}

emit_merge_fail() {
  local ts="$1"
  local why="$2"
  local line="{\"ts\":\"$ts\",\"event\":\"merge_fail\",\"source\":\"client_heartbeat\",\"why\":\"$why\"}"
  append_local "$line"
}

while true; do
  ts="$(date -Iseconds)"
  now_epoch="$(date +%s)"
  start_ns="$(date +%s%N)"

  # ====== 중요: set -e 영향 없이 rc를 정확히 캡처 ======
  set +e
  timeout "$TIMEOUT_SEC" /usr/bin/python3 "$BASE_DIR/run_client.py" --ping --ping_timeout_ms "$PING_TIMEOUT_MS" >/dev/null 2>&1
  rc=$?
  set -e
  # =======================================================

  end_ns="$(date +%s%N)"
  rtt_ms=$(( (end_ns - start_ns) / 1000000 ))

  if [[ "$rc" -eq 0 ]]; then
    fail=0

    # 로컬 OK는 60초에 1번만
    if (( now_epoch - last_ok_local >= OK_LOCAL_EVERY_SEC )); then
      line="{\"ts\":\"$ts\",\"event\":\"heartbeat_ok\",\"source\":\"client_heartbeat\",\"rc\":$rc,\"rtt_ms\":$rtt_ms}"
      append_local "$line"
      last_ok_local="$now_epoch"
    fi

    # 서버로 OK 전송은 기본 OFF(0). 켤 경우에도 5분 1회.
    if [[ "$SEND_OK_TO_SERVER" == "1" ]]; then
      if (( now_epoch - last_ok_send >= OK_SERVER_EVERY_SEC )); then
        line="{\"ts\":\"$ts\",\"event\":\"heartbeat_ok\",\"source\":\"client_heartbeat\",\"rc\":$rc,\"rtt_ms\":$rtt_ms}"
        if ! append_server "$line"; then
          emit_merge_fail "$ts" "ssh_append_failed_ok"
        else
          last_ok_send="$now_epoch"
        fi
      fi
    fi

  else
    fail=$((fail+1))
    line="{\"ts\":\"$ts\",\"event\":\"heartbeat_fail\",\"source\":\"client_heartbeat\",\"rc\":$rc,\"rtt_ms\":$rtt_ms,\"fail_streak\":$fail}"
    append_local "$line"
    if ! append_server "$line"; then
      emit_merge_fail "$ts" "ssh_append_failed_fail"
    fi

    if [[ "$fail" -ge "$FAIL_N" ]]; then
      line2="{\"ts\":\"$ts\",\"event\":\"hang_suspected\",\"source\":\"client_heartbeat\",\"fail_streak\":$fail,\"timeout_sec\":$TIMEOUT_SEC,\"interval_sec\":$INTERVAL_SEC}"
      append_local "$line2"
      if ! append_server "$line2"; then
        emit_merge_fail "$ts" "ssh_append_failed_hang"
      fi
      fail=0
    fi
  fi

  sleep "$INTERVAL_SEC"
done
