#!/usr/bin/env python3
import argparse
import json
import statistics
from pathlib import Path
from collections import Counter, defaultdict

STRICT_KEYS = ("door", "seat_status", "seat_level")

def load_jsonl(path: Path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for ln_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception as e:
                items.append({"_parse_error": str(e), "_line_no": ln_no, "_raw": line})
    return items

def is_strict_valid(case: dict) -> bool:
    if case.get("door") not in ("OPEN", "CLOSE"):
        return False
    ss = case.get("seat_status")
    sl = case.get("seat_level")
    if not (isinstance(ss, list) and len(ss) == 7 and all(x in (0, 1) for x in ss)):
        return False
    if not (isinstance(sl, list) and len(sl) == 7 and all(isinstance(x, int) and 0 <= x <= 255 for x in sl)):
        return False
    return True

def infer_mutation_category(case: dict) -> str:
    """
    _meta가 없거나 불완전해도 대략적인 카테고리를 추정한다.
    - overflow: seat_level에 0..255 벗어난 int가 존재하거나 음수
    - length: seat_status/seat_level 길이 != 7
    - type: seat_status/seat_level 타입이 list가 아니거나 내부 타입이 이상
    - missing: required key 누락
    - semantic: door 값은 OPEN/CLOSE인데 조합이 이상(여긴 규칙이 없으니 fallback)
    """
    # 1) missing
    for k in STRICT_KEYS:
        if k not in case:
            return "missing"

    door = case.get("door")
    ss = case.get("seat_status")
    sl = case.get("seat_level")

    # 2) type
    if not isinstance(ss, list) or not isinstance(sl, list):
        return "type"

    # 3) length
    if len(ss) != 7 or len(sl) != 7:
        return "length"

    # 4) overflow (seat_level)
    overflow = False
    for x in sl:
        if not isinstance(x, int):
            # float/str/null이면 type로 보는 게 맞지만,
            # 여기선 length는 통과했으니 type로 분류
            return "type"
        if x < 0 or x > 255:
            overflow = True
    if overflow:
        return "overflow"

    # 5) seat_status 내용 체크 (0/1이 아니면 type에 가까움)
    for x in ss:
        if x not in (0, 1):
            return "type"

    # 여기까지면 strict valid일 가능성이 큼
    if door not in ("OPEN", "CLOSE"):
        return "type"

    # strict valid이면 valid 반환
    if is_strict_valid(case):
        return "valid"

    return "semantic_or_unknown"

def safe_stats(values):
    if not values:
        return None
    values_sorted = sorted(values)
    return {
        "n": len(values),
        "avg": round(sum(values) / len(values), 3),
        "median": round(statistics.median(values_sorted), 3),
        "min": round(values_sorted[0], 3),
        "max": round(values_sorted[-1], 3),
    }

def print_stats_block(title, rows):
    # rows: list of dicts with elapsed_sec and ok
    times_all = [r["elapsed_sec"] for r in rows if isinstance(r.get("elapsed_sec"), (int, float))]
    times_ok = [r["elapsed_sec"] for r in rows if r.get("ok") is True and isinstance(r.get("elapsed_sec"), (int, float))]
    ok_cnt = sum(1 for r in rows if r.get("ok") is True)
    total = len(rows)

    print(f"\n== {title} ==")
    print(f"total: {total}")
    print(f"  ok: {ok_cnt}")
    st_all = safe_stats(times_all)
    st_ok = safe_stats(times_ok)
    if st_all:
        print(f"time(all): n={st_all['n']} avg={st_all['avg']}s median={st_all['median']}s min={st_all['min']}s max={st_all['max']}s")
    else:
        print("time(all): n=0")
    if st_ok:
        print(f"time(ok):  n={st_ok['n']} avg={st_ok['avg']}s median={st_ok['median']}s min={st_ok['min']}s max={st_ok['max']}s")
    else:
        print("time(ok):  n=0")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="e.g., testcases_trackA.jsonl")
    ap.add_argument("--replay", required=True, help="e.g., replay_trackA_log.jsonl")
    ap.add_argument("--topk", type=int, default=10, help="top-k categories to print")
    args = ap.parse_args()

    cases_path = Path(args.cases)
    replay_path = Path(args.replay)

    cases = load_jsonl(cases_path)
    replay = load_jsonl(replay_path)

    # cases: idx가 없을 수도 있으니 line-order idx로 강제 부여
    # run_testcases.py는 idx를 1부터 기록했으므로 동일하게 맞춤
    idx_to_case = {}
    for i, c in enumerate(cases, 1):
        c["_idx"] = i
        idx_to_case[i] = c

    # replay: idx 필드로 매칭
    idx_to_replay = {}
    for r in replay:
        idx = r.get("idx")
        if isinstance(idx, int):
            idx_to_replay[idx] = r

    mapped = []
    for i in range(1, len(cases) + 1):
        c = idx_to_case.get(i, {})
        r = idx_to_replay.get(i)
        if not r:
            mapped.append({
                "idx": i,
                "case": c,
                "ok": False,
                "status": "missing_replay",
                "elapsed_sec": None,
            })
        else:
            mapped.append({
                "idx": i,
                "case": c,
                "ok": r.get("ok"),
                "status": r.get("status") or r.get("callstatus_status") or "unknown",
                "elapsed_sec": r.get("elapsed_sec"),
                "oracle": r.get("oracle"),
                "returncode": r.get("returncode"),
                "callstatus_last": r.get("callstatus_last"),
                "callstatus_status": r.get("callstatus_status"),
                "proc_ok": r.get("proc_ok"),
                "callstatus_ok": r.get("callstatus_ok"),
            })

    # 케이스 mix
    strict_valid_cnt = 0
    mutated_cnt = 0
    mutation_counts = Counter()

    # status 분포
    status_counts_all = Counter()
    status_counts_valid = Counter()
    status_counts_mut = Counter()

    # 카테고리별 rows 수집
    cat_rows = defaultdict(list)

    rows_all = []
    rows_strict = []
    rows_mut = []

    for row in mapped:
        c = row["case"]
        strict_ok = is_strict_valid(c)

        # 카테고리 결정: _meta 우선, 없으면 추정
        meta = c.get("_meta", {})
        if isinstance(meta, dict) and "mutation_category" in meta:
            cat = meta.get("mutation_category") or "unknown"
        else:
            cat = infer_mutation_category(c)

        mutation_counts[cat] += 1

        if strict_ok:
            strict_valid_cnt += 1
            rows_strict.append(row)
            status_counts_valid[row["status"]] += 1
        else:
            mutated_cnt += 1
            rows_mut.append(row)
            status_counts_mut[row["status"]] += 1

        rows_all.append(row)
        status_counts_all[row["status"]] += 1
        cat_rows[cat].append(row)

    print("==== Track A Summary ====")
    print(f"cases_file:  {cases_path}")
    print(f"replay_file: {replay_path}")
    print(f"mapped_cases: {len(mapped)}/{len(cases)}")

    print("\ncase_mix:")
    print(f"  strict_valid: {strict_valid_cnt}")
    print(f"  mutated: {mutated_cnt}")

    print("\nmutation_category_counts:")
    for k, v in mutation_counts.most_common():
        print(f"  {k}: {v}")

    print("\nstatus_counts (ALL):")
    for k, v in status_counts_all.most_common():
        print(f"  {k}: {v}")

    print("\nstatus_counts (STRICT_VALID_ONLY):")
    for k, v in status_counts_valid.most_common():
        print(f"  {k}: {v}")

    print("\nstatus_counts (MUTATED_ONLY):")
    for k, v in status_counts_mut.most_common():
        print(f"  {k}: {v}")

    # 시간 통계
    print_stats_block("ALL", rows_all)
    print_stats_block("STRICT_VALID_ONLY", rows_strict)
    print_stats_block("MUTATED_ONLY", rows_mut)

    # 카테고리별 top-k
    print("\n== Per-Category (top) ==")
    for cat, _ in mutation_counts.most_common(args.topk):
        print_stats_block(f"CATEGORY::{cat}", cat_rows[cat])

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
