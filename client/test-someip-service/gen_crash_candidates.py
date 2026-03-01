#!/usr/bin/env python3
import json
import random
from pathlib import Path

random.seed(7)

def w(obj):
    return json.dumps(obj, ensure_ascii=False)

def main():
    out_path = Path("testcases_crash_candidates.jsonl")
    cases = []

    # 0) Baseline (정상) 3개: 비교 기준
    cases += [
        {"door": "OPEN",  "seat_status": [0,0,0,0,0,0,0], "seat_level": [0,0,0,0,0,0,0]},
        {"door": "CLOSE", "seat_status": [1,1,1,1,1,1,1], "seat_level": [255,255,255,255,255,255,255]},
        {"door": "OPEN",  "seat_status": [1,0,1,0,1,0,1], "seat_level": [0,255,0,255,0,255,0]},
    ]

    # 1) overflow/underflow: 길이 7 유지, 값만 비정상 (원인귀속 쉬움)
    cases += [
        {"door": "OPEN",  "seat_status": [1,0,1,0,1,0,1], "seat_level": [256,0,0,0,0,0,0]},
        {"door": "CLOSE", "seat_status": [0,1,0,1,0,1,0], "seat_level": [-1,255,255,255,255,255,255]},
        {"door": "OPEN",  "seat_status": [1,1,1,1,1,1,1], "seat_level": [999999,1,1,1,1,1,1]},
        {"door": "CLOSE", "seat_status": [0,0,0,0,0,0,0], "seat_level": [-999999,2,2,2,2,2,2]},
    ]

    # 2) length: 길이 자체를 깨기 (파서/루프가 취약하면 여기서 터짐)
    #   - run_testcases.py는 길이 체크를 하지 않고 CSV로 넘기므로,
    #     PlaygroundClient 내부 파싱이 취약하면 크래시 후보가 됩니다.
    cases += [
        {"door": "OPEN",  "seat_status": [1,0,1,0,1,0],       "seat_level": [10,20,30,40,50,60,70]},      # seat_status 6
        {"door": "CLOSE", "seat_status": [1,0,1,0,1,0,1,0],   "seat_level": [10,20,30,40,50,60,70]},      # seat_status 8
        {"door": "OPEN",  "seat_status": [1,0,1,0,1,0,1],     "seat_level": [10,20,30,40,50,60]},         # seat_level 6
        {"door": "CLOSE", "seat_status": [1,0,1,0,1,0,1],     "seat_level": [10,20,30,40,50,60,70,80]},   # seat_level 8
    ]

    # 3) extreme length: 길이를 과하게 늘려서 파서/버퍼 취약점 후보
    #    (다음 주 보고용이라 너무 과격하면 50~100 정도로 제한 추천)
    long_status = [1 if i % 2 == 0 else 0 for i in range(80)]
    long_level  = [255 for _ in range(80)]
    cases += [
        {"door": "OPEN",  "seat_status": long_status, "seat_level": [0,0,0,0,0,0,0]},   # status만 80
        {"door": "CLOSE", "seat_status": [1,0,1,0,1,0,1], "seat_level": long_level},    # level만 80
    ]

    # 4) semantic odd (구조는 정상이나 조합이 이상): 서버 상태머신/검증 로직이 약하면 문제 유발
    cases += [
        {"door": "OPEN",  "seat_status": [1,1,1,1,1,1,1], "seat_level": [0,0,0,0,0,0,0]},       # ON인데 레벨 0
        {"door": "CLOSE", "seat_status": [0,0,0,0,0,0,0], "seat_level": [255,255,255,255,255,255,255]}, # OFF인데 레벨 255
    ]

    # 5) random fuzz (하지만 “한 번에 한 규칙” 유지: 값 범위만 흔들기)
    for _ in range(6):
        ss = [random.choice([0,1]) for _ in range(7)]
        # 일부러 범위를 벗어나게 섞되, 한두 개만 벗어나게
        sl = [random.randint(0,255) for _ in range(7)]
        j = random.randrange(7)
        sl[j] = random.choice([256, -1, 1000000, -1000000])
        cases.append({"door": random.choice(["OPEN","CLOSE"]), "seat_status": ss, "seat_level": sl})

    # 저장
    with open(out_path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(w(c) + "\n")

    print(f"[OK] wrote {len(cases)} cases -> {out_path}")

if __name__ == "__main__":
    main()
