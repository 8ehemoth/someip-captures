#!/usr/bin/env bash
set -euo pipefail

HOOK_SO="$PWD/fuzz/hooks/hook_sendto.so"
OUT_JSONL="$PWD/fuzz/results/results.jsonl"
mkdir -p "$(dirname "$OUT_JSONL")" "$PWD/fuzz/logs"

N="${1:-200}"
SKIP="${FUZZ_SKIP:-32}"
FLIPS="${FUZZ_NFLIPS:-1}"

for i in $(seq 1 "$N"); do
  SEED="$i"
  START_NS=$(date +%s%N)

  # Run client with hook
  LOG_OUT="$PWD/fuzz/logs/client_${i}.log"
  LOG_ERR="$PWD/fuzz/logs/hook_${i}.err"

  FUZZ_ENABLE=1 FUZZ_SEED="$SEED" FUZZ_SKIP="$SKIP" FUZZ_NFLIPS="$FLIPS" \
  LD_PRELOAD="$HOOK_SO" \
  python3 run_client.py >"$LOG_OUT" 2>"$LOG_ERR" || true

  END_NS=$(date +%s%N)
  DUR_MS=$(( (END_NS - START_NS) / 1000000 ))

  # Oracle from client log
  AVAIL=$(grep -c "Available\." "$LOG_OUT" || true)
  CS0_1=$(grep -c "changeDoorsState(OPEN) CallStatus=0" "$LOG_OUT" || true)
  CS0_2=$(grep -c "setSeatHeatingStatusAttribute(size=7) CallStatus=0" "$LOG_OUT" || true)
  CS0_3=$(grep -c "setSeatHeatingLevelAttribute(size=7) CallStatus=0" "$LOG_OUT" || true)

  # Any non-zero CallStatus?
  CS_BAD_LINE=$(grep -n "CallStatus=[^0]" "$LOG_OUT" | head -n 1 || true)

  STATUS="ok"
  if [ "$AVAIL" -eq 0 ]; then STATUS="not_available"; fi
  if [ -n "$CS_BAD_LINE" ]; then STATUS="callstatus_nonzero"; fi
  if [ "$CS0_1" -eq 0 ] || [ "$CS0_2" -eq 0 ] || [ "$CS0_3" -eq 0 ]; then
    # if missing success lines but no explicit nonzero, treat as abnormal/timeout-ish
    if [ "$STATUS" = "ok" ]; then STATUS="missing_success"; fi
  fi

  printf '{"i":%d,"fuzz_seed":%d,"skip":%d,"flips":%d,"duration_ms":%d,"status":"%s","nonzero_line":"%s"}\n' \
    "$i" "$SEED" "$SKIP" "$FLIPS" "$DUR_MS" "$STATUS" "${CS_BAD_LINE//\"/\\\"}" >> "$OUT_JSONL"

  echo "[$i/$N] $STATUS (${DUR_MS}ms)"
done
