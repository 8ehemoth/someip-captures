#!/usr/bin/env python3
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

def valid(obj) -> bool:
    if obj.get("door") not in ("OPEN", "CLOSE"):
        return False
    ss = obj.get("seat_status")
    sl = obj.get("seat_level")
    if not (isinstance(ss, list) and len(ss) == 7 and all(x in (0, 1) for x in ss)):
        return False
    if not (isinstance(sl, list) and len(sl) == 7 and all(isinstance(x, int) and 0 <= x <= 255 for x in sl)):
        return False
    return True

def parse_jsonl_lines(text: str):
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if not (ln.startswith("{") and ln.endswith("}")):
            continue
        try:
            obj = json.loads(ln)
            if valid(obj):
                out.append(obj)
        except Exception:
            continue
    return out

def main():
    # .env 로딩을 "스크립트 위치 기준"으로 고정 (cwd 영향 제거)
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in .env (script directory)")

    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    out_path = Path(os.getenv("OUT_PATH", str(base_dir / "testcases.jsonl")))
    n_cases = int(os.getenv("N_CASES", "30"))

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You are a test case generator for an automotive SOME/IP client.\n"
        "Return ONLY JSON Lines (JSONL). No markdown, no explanations.\n"
        "Each line must be one JSON object with schema:\n"
        "{\n"
        '  "door": "OPEN" | "CLOSE",\n'
        '  "seat_status": [7 integers each 0 or 1],\n'
        '  "seat_level": [7 integers each 0..255]\n'
        "}\n"
        "Rules:\n"
        "- Output exactly the requested number of JSONL lines.\n"
        "- seat_status length must be exactly 7.\n"
        "- seat_level length must be exactly 7.\n"
        "- Include boundary values 0 and 255 sometimes.\n"
        "- Ensure diversity across lines.\n"
    )

    cases = []
    max_rounds = 6  # 부족하면 추가 생성하는 재시도 횟수
    round_id = 0

    while len(cases) < n_cases and round_id < max_rounds:
        round_id += 1
        need = n_cases - len(cases)

        user_prompt = (
            f"Generate exactly {need} diverse test cases as JSONL.\n"
            "Vary door state and seat combinations.\n"
            "Use boundary values (0 and 255) occasionally.\n"
            "Return exactly the lines, nothing else.\n"
        )

        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        new_cases = parse_jsonl_lines(resp.output_text or "")
        # 중복 제거(완전 동일 객체 기준)
        existing = {json.dumps(c, sort_keys=True) for c in cases}
        for c in new_cases:
            key = json.dumps(c, sort_keys=True)
            if key not in existing:
                cases.append(c)
                existing.add(key)
            if len(cases) >= n_cases:
                break

    # 저장
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for c in cases[:n_cases]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"[OK] model={model} wrote={min(len(cases), n_cases)}/{n_cases} -> {out_path}")
    if len(cases) < n_cases:
        print("[WARN] Could not reach target count. Re-run or increase max_rounds.")

if __name__ == "__main__":
    main()
