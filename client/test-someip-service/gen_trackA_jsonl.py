#!/usr/bin/env python3
import os
import json
import argparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

EXACT_KEYS = {"door", "seat_status", "seat_level"}


def is_exact_int(x) -> bool:
    return type(x) is int


def is_schema_safe(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if set(obj.keys()) != EXACT_KEYS:
        return False
    if obj.get("door") not in ("OPEN", "CLOSE"):
        return False

    ss = obj.get("seat_status")
    sl = obj.get("seat_level")

    if not (isinstance(ss, list) and all(is_exact_int(x) for x in ss)):
        return False
    if not (isinstance(sl, list) and all(is_exact_int(x) for x in sl)):
        return False
    return True


def is_strict_valid(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if set(obj.keys()) != EXACT_KEYS:
        return False
    if obj.get("door") not in ("OPEN", "CLOSE"):
        return False

    ss = obj.get("seat_status")
    sl = obj.get("seat_level")

    if not (
        isinstance(ss, list)
        and len(ss) == 7
        and all(is_exact_int(x) and x in (0, 1) for x in ss)
    ):
        return False

    if not (
        isinstance(sl, list)
        and len(sl) == 7
        and all(is_exact_int(x) and 0 <= x <= 255 for x in sl)
    ):
        return False

    return True


def parse_jsonl_lines_keep_all(text: str):
    out = []
    for ln in (text or "").splitlines():
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


def canonical_case(obj: dict) -> dict:
    return {
        "door": obj["door"],
        "seat_status": list(obj["seat_status"]),
        "seat_level": list(obj["seat_level"]),
    }


def case_key(obj: dict) -> str:
    canon = canonical_case(obj)
    return json.dumps(canon, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def extract_output_text(resp) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text

    parts = []
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            t = getattr(content, "text", None)
            if isinstance(t, str):
                parts.append(t)
            else:
                value = getattr(t, "value", None)
                if isinstance(value, str):
                    parts.append(value)

    return "\n".join(parts).strip()


def profile_prompt(profile: str) -> str:
    if profile == "edge-heavy":
        return (
            "Focus strongly on edge-heavy values. "
            "Use 0,1,2,253,254,255 frequently. "
            "Prefer all-zero, all-255, alternating, ramp, plateau, and spike patterns. "
            "Avoid mild mid-range values unless needed for contrast."
        )
    elif profile == "replay-heavy":
        return (
            "Focus on replay-heavy and near-duplicate cases. "
            "Repeat extreme patterns many times with only tiny variations. "
            "Stress repeated handling of very similar but still valid payloads."
        )
    elif profile == "semantic-odd":
        return (
            "Focus on semantically odd but schema-valid combinations. "
            "Examples: seat_status values of 1 with seat_level 0, "
            "or seat_status values of 0 with seat_level 255. "
            "Make the combinations behaviorally strange while staying fully valid."
        )
    elif profile == "mixed-strong":
        return (
            "Combine edge-heavy, replay-heavy, and semantically odd strategies. "
            "Maximize behavioral diversity while keeping every case fully strict-valid."
        )
    else:
        return "Generate diverse strict-valid server-reaching cases."


def build_system_prompt(profile: str, user_goal: str) -> str:
    return (
        "You generate SOME/IP payload-only fuzzing test cases as JSON Lines (JSONL).\n"
        "Return JSONL only. No markdown, no explanations, no numbering, no code fences.\n\n"
        "Each line must be exactly one JSON object with these keys only:\n"
        '- "door"\n'
        '- "seat_status"\n'
        '- "seat_level"\n\n'
        "Strict schema requirements for EVERY line:\n"
        '- "door" must be exactly "OPEN" or "CLOSE"\n'
        '- "seat_status" must be a JSON array of exactly 7 integers\n'
        '- each seat_status value must be either 0 or 1\n'
        '- "seat_level" must be a JSON array of exactly 7 integers\n'
        "- each seat_level value must be between 0 and 255 inclusive\n"
        "- do not output any extra keys\n"
        "- do not use null, strings, floats, booleans, objects, nested arrays\n\n"
        "Goal:\n"
        "Generate diverse but strictly valid cases that are likely to reach the server "
        "while stressing server-side logic as much as possible.\n\n"
        f"Profile guidance:\n{profile_prompt(profile)}\n\n"
        f"Additional user goal:\n{user_goal}\n\n"
        "Use patterns such as:\n"
        "- all zeros / all ones\n"
        "- single-hot or single-spike positions\n"
        "- alternating patterns\n"
        "- ascending ramps / descending ramps\n"
        "- plateaus with one or two outliers\n"
        "- symmetric patterns\n"
        "- front-heavy / back-heavy patterns\n"
        "- near-boundary values such as 0,1,2,253,254,255\n"
        "- semantically odd combinations such as seat_status=1 with seat_level=0\n\n"
        "Rules:\n"
        "- Output exactly the requested number of JSONL lines.\n"
        "- Avoid duplicates as much as possible unless replay-heavy behavior is requested.\n"
        "- Keep OPEN and CLOSE reasonably balanced.\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--profile",
        choices=["edge-heavy", "replay-heavy", "semantic-odd", "mixed-strong"],
        default="mixed-strong",
        help="생성 스타일",
    )
    ap.add_argument(
        "--goal",
        default="Generate strict-valid server-reaching cases that are stronger than normal server_reach inputs.",
        help="추가 생성 목표 문장",
    )
    ap.add_argument("--max_rounds", type=int, default=8)
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in .env (script directory)")

    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    n_cases = args.n if args.n is not None else int(os.getenv("N_CASES", "60"))
    out_path = Path(
        args.out if args.out is not None else os.getenv("OUT_PATH", str(base_dir / "testcases_trackA.jsonl"))
    )

    client = OpenAI(api_key=api_key)
    system_prompt = build_system_prompt(args.profile, args.goal)

    cases = []
    existing = set()
    round_id = 0

    while len(cases) < n_cases and round_id < args.max_rounds:
        round_id += 1
        need = n_cases - len(cases)

        user_prompt = (
            f"Generate exactly {need} test cases as JSONL.\n"
            "Return exactly JSON lines, nothing else.\n"
        )

        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        text = extract_output_text(resp)
        new_cases = parse_jsonl_lines_keep_all(text)

        for c in new_cases:
            if not is_schema_safe(c):
                continue
            if not is_strict_valid(c):
                continue

            key = case_key(c)
            if key in existing:
                continue

            canon = canonical_case(c)
            cases.append(canon)
            existing.add(key)

            if len(cases) >= n_cases:
                break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for c in cases[:n_cases]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"[OK] profile={args.profile} model={model} wrote={len(cases)}/{n_cases} -> {out_path}")
    if len(cases) < n_cases:
        print("[WARN] Could not reach target count. Re-run or increase --max_rounds.")


if __name__ == "__main__":
    main()
