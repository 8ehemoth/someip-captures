#!/usr/bin/env python3
import json
import os
import re
import argparse
from pathlib import Path
from collections import Counter, defaultdict

ROUTING_ERR_PAT = re.compile(r"configured as routing|routing manager present|Won't instantiate routing", re.I)

def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                # 깨진 라인이 있어도 분석은 계속
                rows.append({"_parse_error_line": ln})
    return rows

def get_case_from_log_row(r):
    # 로그에 케이스가 같이 들어있는 경우 대비(키 후보들)
    for k in ("case", "testcase", "input", "payload", "req", "data"):
        v = r.get(k)
        if isinstance(v, dict) and ("door" in v or "seat_status" in v or "seat_level" in v):
            return v
    return None

def get_idx(r, fallback):
    for k in ("idx", "i", "case_idx", "caseId"):
        if isinstance(r.get(k), int):
            return r[k]
        if isinstance(r.get(k), str) and r[k].isdigit():
            return int(r[k])
    return fallback

def classify(r):
    """
    reason 우선순위:
    - timeout
    - infra_routing_conflict (클라 설정 충돌)
    - server_health_bad (서버 죽음/포트/치명 로그)
    - returncode_nonzero
    - callstatus_missing / callstatus_nonzero
    - ok_false_other
    """
    status = r.get("status")
    if status == "timeout":
        return "timeout"

    out_tail = r.get("output_tail") or r.get("stdout_tail") or ""
    if isinstance(out_tail, str) and ROUTING_ERR_PAT.search(out_tail):
        return "infra_routing_conflict"

    # 서버 헬스(키 후보들)
    sh = None
    for k in ("server_health_after", "server_health", "server_after", "health_after"):
        if isinstance(r.get(k), dict):
            sh = r[k]
            break

    if isinstance(sh, dict):
        # run_testcases.py에서 _ok, server_alive, port_ok, fatal_seen 등 기록하는 패턴을 가정
        if (sh.get("_ok") is False) or (sh.get("server_alive") is False) or (sh.get("port_ok") is False) or (sh.get("fatal_seen") is True):
            return "server_health_bad"

    oracle = r.get("oracle", {}) if isinstance(r.get("oracle"), dict) else {}
    rc = oracle.get("returncode")
    if isinstance(rc, int) and rc != 0:
        return "returncode_nonzero"

    if oracle.get("mode") == "callstatus":
        cs = oracle.get("callstatus", {})
        if isinstance(cs, dict):
            if cs.get("found") is False:
                return "callstatus_missing"
            vals = cs.get("values")
            if isinstance(vals, list) and any(isinstance(v, int) and v != 0 for v in vals):
                return "callstatus_nonzero"

    # 마지막으로 ok=False면 기타 실패
    if r.get("ok") is False:
        return "ok_false_other"

    return "ok"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", default="replay_log_trackA.jsonl")
    ap.add_argument("--cases", default="testcases_trackA.jsonl", help="원본 testcase JSONL (idx=라인번호 가정)")
    ap.add_argument("--outdir", default="analysis_out")
    ap.add_argument("--server_host", default=os.getenv("SERVER_HOST", "192.168.40.134"))
    ap.add_argument("--server_user", default=os.getenv("SERVER_USER", "server"))
    ap.add_argument("--delay", default=os.getenv("DELAY", "0.5"))
    args = ap.parse_args()

    replay_path = Path(args.replay)
    cases_path = Path(args.cases)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(replay_path)
    cases = load_jsonl(cases_path)

    reason_cnt = Counter()
    ok_cnt = Counter()
    suspicious = []

    # 서버 재시작 감지(가능하면): before/after pid 비교
    restart_hits = 0

    for n, r in enumerate(rows, start=1):
        idx = get_idx(r, n)
        ok = r.get("ok")
        ok_cnt[str(ok)] += 1

        reason = classify(r)
        reason_cnt[reason] += 1

        # 서버 재시작(있을 때만)
        shb = r.get("server_health_before") if isinstance(r.get("server_health_before"), dict) else None
        sha = None
        for k in ("server_health_after", "server_health", "server_after", "health_after"):
            if isinstance(r.get(k), dict):
                sha = r[k]
                break
        if isinstance(shb, dict) and isinstance(sha, dict):
            pb = shb.get("pid")
            pa = sha.get("pid")
            if isinstance(pb, int) and isinstance(pa, int) and pb != pa:
                restart_hits += 1

        if reason != "ok":
            # 케이스 확보(로그에 없으면 원본 testcase에서 idx번째 줄 사용)
            case_obj = get_case_from_log_row(r)
            if case_obj is None and 1 <= idx <= len(cases) and isinstance(cases[idx - 1], dict):
                case_obj = cases[idx - 1]

            oracle = r.get("oracle", {}) if isinstance(r.get("oracle"), dict) else {}
            entry = {
                "idx": idx,
                "reason": reason,
                "ok": ok,
                "t": r.get("t"),
                "status": r.get("status"),
                "oracle": {
                    "mode": oracle.get("mode"),
                    "returncode": oracle.get("returncode"),
                    "callstatus": oracle.get("callstatus"),
                },
                "server_health": sha,
                "output_tail": (r.get("output_tail") or "")[:900],
                "case": case_obj,
            }
            suspicious.append(entry)

    # 요약 출력
    print("==============================================")
    print(f"[SUMMARY] replay={replay_path} cases={cases_path}")
    print(f"[COUNT] total={len(rows)}  ok_true={ok_cnt.get('True',0)}  ok_false={ok_cnt.get('False',0)}  ok_none={ok_cnt.get('None',0)}")
    print("[REASON TOP]")
    for k, v in reason_cnt.most_common():
        print(f"  - {k}: {v}")
    if restart_hits:
        print(f"[SERVER_RESTART_DETECTED] {restart_hits} cases had pid change (before!=after)")
    print("==============================================")

    # suspicious 저장
    sus_path = outdir / "suspicious.jsonl"
    with sus_path.open("w", encoding="utf-8") as f:
        for e in suspicious:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"[WRITE] {sus_path}  (n={len(suspicious)})")

    # 재현용 케이스 파일 생성(1개=1줄 JSONL)
    repro_cases_dir = outdir / "repro_cases"
    repro_logs_dir = outdir / "repro_logs"
    repro_cases_dir.mkdir(parents=True, exist_ok=True)
    repro_logs_dir.mkdir(parents=True, exist_ok=True)

    made = 0
    for e in suspicious:
        if not isinstance(e.get("case"), dict):
            continue
        idx = e["idx"]
        p = repro_cases_dir / f"idx_{idx:03d}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            f.write(json.dumps(e["case"], ensure_ascii=False) + "\n")
        made += 1

    # 재현 스크립트 생성
    repro_sh = outdir / "repro_suspicious.sh"
    repro_sh.write_text(
f"""#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$BASE_DIR/.." && pwd)"

SERVER_HOST="${{SERVER_HOST:-{args.server_host}}}"
SERVER_USER="${{SERVER_USER:-{args.server_user}}}"
DELAY="${{DELAY:-{args.delay}}}"

echo "[repro] SERVER_HOST=$SERVER_HOST SERVER_USER=$SERVER_USER DELAY=$DELAY"
echo "[repro] cases dir: $BASE_DIR/repro_cases"
echo

mkdir -p "$BASE_DIR/repro_logs"

for f in "$BASE_DIR"/repro_cases/idx_*.jsonl; do
  idx="$(basename "$f" .jsonl | cut -d_ -f2)"
  echo "=== REPRO idx=$idx file=$f ==="
  python3 "$ROOT/run_testcases.py" \\
    --jsonl "$f" \\
    --use_run_client_wrapper \\
    --oracle callstatus \\
    --server_host "$SERVER_HOST" \\
    --server_user "$SERVER_USER" \\
    --log "$BASE_DIR/repro_logs/repro_${{idx}}.jsonl" \\
    --delay "$DELAY"
done

echo "[repro] done"
""",
        encoding="utf-8"
    )
    os.chmod(repro_sh, 0o755)

    print(f"[WRITE] {repro_cases_dir}  (made={made} one-line jsonl files)")
    print(f"[WRITE] {repro_sh}")
    print()
    print("Next:")
    print(f"  1) python3 analyze_replay.py --replay {replay_path} --cases {cases_path}")
    print(f"  2) bash {repro_sh}   # suspicious 케이스만 1개씩 재현")

if __name__ == "__main__":
    main()
