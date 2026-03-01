#!/usr/bin/env python3
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def is_strict_valid(obj) -> bool:
    if obj.get("door") not in ("OPEN", "CLOSE"):
        return False

    ss = obj.get("seat_status")
    sl = obj.get("seat_level")

    if not (isinstance(ss, list) and len(ss) == 7 and all(x in (0, 1) for x in ss)):
        return False
    if not (isinstance(sl, list) and len(sl) == 7 and all(isinstance(x, int) and 0 <= x <= 255 for x in sl)):
        return False

    return True


def parse_jsonl_lines_keep_all(text: str):
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if not (ln.startswith("{") and ln.endswith("}")):
            continue
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def main():
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in .env (script directory)")

    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    out_path = Path(os.getenv("OUT_PATH", str(base_dir / "testcases_trackA.jsonl")))
    n_cases = int(os.getenv("N_CASES", "60"))

    pct_valid = int(os.getenv("PCT_VALID", "40"))
    if pct_valid < 0:
        pct_valid = 0
    if pct_valid > 100:
        pct_valid = 100
    pct_invalid = 100 - pct_valid

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You generate SOME/IP client test cases as JSON Lines (JSONL). Return JSONL only.\n"
        "Each line must be ONE JSON object with keys:\n"
        "- door\n"
        "- seat_status\n"
        "- seat_level\n\n"
        "You MUST generate a mix of VALID and MUTATED cases.\n"
        f"- About {pct_valid}% should be strictly VALID:\n"
        "  door in {OPEN,CLOSE}; seat_status length=7 values in {0,1}; seat_level length=7 integers 0..255\n"
        f"- About {pct_invalid}% should be MUTATED (intentionally violate ONE rule per case).\n\n"
        "IMPORTANT CONSTRAINT (for replay via CLI):\n"
        "- NEVER omit keys (no missing fields).\n"
        "- NEVER use wrong types like strings/null/nested objects.\n"
        "- Always keep door as OPEN or CLOSE.\n"
        "- Always keep seat_status and seat_level as JSON arrays.\n\n"
        "Allowed mutation categories (choose EXACTLY ONE per mutated case):\n"
        "1) overflow: seat_level contains out-of-range ints like 256, 999, -1 (keep list length 7)\n"
        "2) length: seat_status or seat_level length not 7 (e.g., 6 or 8). Values remain ints.\n"
        "3) boundary: still valid ranges but extreme patterns (all 0, all 255, alternating, etc.)\n"
        "4) semantic: keep structure but make odd combinations (e.g., all heaters ON with all levels 0)\n\n"
        "Rules:\n"
        "- Output exactly the requested number of JSONL lines.\n"
        "- For mutated cases, mutate ONLY one aspect (so we can attribute failures).\n"
        "- Keep diversity; avoid duplicates.\n"
    )

    cases = []
    max_rounds = 8
    round_id = 0

    while len(cases) < n_cases and round_id < max_rounds:
        round_id += 1
        need = n_cases - len(cases)

        user_prompt = (
            f"Generate exactly {need} test cases as JSONL.\n"
            "Remember: mix valid and mutated per the system rules.\n"
            "Return exactly JSON lines, nothing else.\n"
        )

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # temperature를 일부 모델(gpt-5 계열)이 허용하지 않아 제거
        )

        text = completion.choices[0].message.content or ""
        new_cases = parse_jsonl_lines_keep_all(text)

        existing = {json.dumps(c, sort_keys=True) for c in cases}
        for c in new_cases:
            key = json.dumps(c, sort_keys=True)
            if key in existing:
                continue

            strict_ok = is_strict_valid(c)
            c["_meta"] = {"strict_valid": strict_ok}

            cases.append(c)
            existing.add(key)
            if len(cases) >= n_cases:
                break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for c in cases[:n_cases]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_written = min(len(cases), n_cases)
    n_strict = sum(1 for c in cases[:n_written] if c.get("_meta", {}).get("strict_valid"))
    print(f"[OK] model={model} wrote={n_written}/{n_cases} -> {out_path}")
    print(f"[STAT] strict_valid={n_strict}, mutated={n_written - n_strict}")
    if len(cases) < n_cases:
        print("[WARN] Could not reach target count. Re-run or increase max_rounds.")


if __name__ == "__main__":
    main()

