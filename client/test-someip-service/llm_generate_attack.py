#!/usr/bin/env python3
"""
llm_generate_attack.py

Generate SOME/IP client test cases (JSONL) in "attack scenario" styles that are
safe to replay with your current pipeline (run_testcases.py + PlaygroundClient CLI).

Design goals:
- Keep schema compatible with run_testcases.py:
  { "door": "OPEN"|"CLOSE", "seat_status": [..], "seat_level": [..] }
- Provide attack-like patterns WITHOUT crafting explicit crash payloads.
  (Replay / burst-stress / semantic-abuse patterns are sufficient to "prove execution"
   in a report, together with wireshark + logs + oracle.)
- Robust parsing/validation, dedup, deterministic fallback if OpenAI is unavailable.
"""

import os
import json
import argparse
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

# Optional deps
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# -----------------------------
# Validation / helpers
# -----------------------------
def is_valid_case(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("door") not in ("OPEN", "CLOSE"):
        return False
    ss = obj.get("seat_status")
    sl = obj.get("seat_level")
    if not (isinstance(ss, list) and len(ss) == 7 and all(x in (0, 1) for x in ss)):
        return False
    if not (isinstance(sl, list) and len(sl) == 7 and all(isinstance(x, int) and 0 <= x <= 255 for x in sl)):
        return False
    return True


def dumps_key(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def parse_jsonl_objects(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if not (ln.startswith("{") and ln.endswith("}")):
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if is_valid_case(obj):
            out.append(obj)
    return out


# -----------------------------
# Local (non-LLM) generator
# -----------------------------
def make_extreme_case(rng: random.Random, door: Optional[str] = None) -> Dict[str, Any]:
    if door is None:
        door = rng.choice(["OPEN", "CLOSE"])
    patterns_status = [
        [0]*7,
        [1]*7,
        [0, 1, 0, 1, 0, 1, 0],
        [1, 0, 1, 0, 1, 0, 1],
    ]
    patterns_level = [
        [0]*7,
        [255]*7,
        [0, 255, 0, 255, 0, 255, 0],
        [255, 0, 255, 0, 255, 0, 255],
        [10, 20, 30, 40, 50, 60, 70],
        [70, 60, 50, 40, 30, 20, 10],
    ]
    ss = rng.choice(patterns_status)
    sl = rng.choice(patterns_level)
    return {"door": door, "seat_status": ss[:], "seat_level": sl[:]}


def make_semantic_abuse_case(rng: random.Random) -> Dict[str, Any]:
    """
    Keep schema valid but create "odd" semantics:
    - heaters ON with level 0
    - heaters OFF with high levels
    - mixed contradictions
    """
    door = rng.choice(["OPEN", "CLOSE"])
    mode = rng.choice(["on_zero", "off_high", "mixed"])
    if mode == "on_zero":
        ss = [1]*7
        sl = [0]*7
    elif mode == "off_high":
        ss = [0]*7
        sl = [255]*7
    else:
        ss = [rng.choice([0, 1]) for _ in range(7)]
        sl = []
        for i in range(7):
            if ss[i] == 1:
                sl.append(rng.choice([0, 1, 2, 5, 10]))
            else:
                sl.append(rng.choice([200, 220, 240, 255]))
    return {"door": door, "seat_status": ss, "seat_level": sl}


def build_attack_suite_local(
    rng: random.Random,
    n_cases: int,
    attack: str,
    repeat_ratio: float,
    burst_block: int,
) -> List[Dict[str, Any]]:
    """
    attack:
      - replay: many identical cases, a few variants
      - stress: bursty extremes, toggling door patterns
      - semantic: semantic abuse cases + some extremes
      - mixed: combination of above
    """
    if n_cases <= 0:
        return []

    cases: List[Dict[str, Any]] = []

    # Base seeds
    base_a = make_extreme_case(rng, door="OPEN")
    base_b = make_extreme_case(rng, door="CLOSE")

    def add_case(c: Dict[str, Any]):
        cases.append(c)

    if attack == "replay":
        # Mostly identical replays
        n_repeat = int(n_cases * max(0.0, min(1.0, repeat_ratio)))
        n_var = n_cases - n_repeat
        for _ in range(n_repeat):
            add_case(base_a)
        for _ in range(n_var):
            c = make_extreme_case(rng)
            # slight variation: flip 1-2 indices
            for _k in range(rng.choice([1, 2])):
                i = rng.randrange(7)
                c["seat_status"][i] ^= 1
                c["seat_level"][i] = rng.choice([0, 255, 10, 200])
            add_case(c)

    elif attack == "stress":
        # Bursty toggles: blocks of repeated patterns
        if burst_block <= 0:
            burst_block = 10
        while len(cases) < n_cases:
            block = min(burst_block, n_cases - len(cases))
            base = base_a if (len(cases) // burst_block) % 2 == 0 else base_b
            for _ in range(block):
                add_case(base)

    elif attack == "semantic":
        # Semantic contradictions + some extremes
        while len(cases) < n_cases:
            if rng.random() < 0.7:
                add_case(make_semantic_abuse_case(rng))
            else:
                add_case(make_extreme_case(rng))

    else:  # mixed
        while len(cases) < n_cases:
            pick = rng.random()
            if pick < 0.4:
                add_case(base_a)
            elif pick < 0.6:
                add_case(make_extreme_case(rng))
            elif pick < 0.85:
                add_case(make_semantic_abuse_case(rng))
            else:
                add_case(base_b)

    # Ensure validity & trim
    out = []
    for c in cases[:n_cases]:
        # copy to avoid shared refs
        cc = {"door": c["door"], "seat_status": list(c["seat_status"]), "seat_level": list(c["seat_level"])}
        if is_valid_case(cc):
            out.append(cc)
    return out


# -----------------------------
# LLM generator
# -----------------------------
def build_prompts(attack: str, need: int, repeat_ratio: float, burst_block: int) -> (str, str):
    # Keep it strictly JSONL and strictly valid schema.
    # Attack is expressed as "scenario style", not as exploit/crash instruction.
    system_prompt = (
        "You generate SOME/IP client test cases as JSON Lines (JSONL).\n"
        "Return ONLY JSONL. No markdown. No explanations.\n\n"
        "Schema per line:\n"
        "{\n"
        '  "door": "OPEN" | "CLOSE",\n'
        '  "seat_status": [7 integers each 0 or 1],\n'
        '  "seat_level": [7 integers each 0..255]\n'
        "}\n\n"
        "Hard constraints:\n"
        "- Output exactly the requested number of lines.\n"
        "- Always include all keys.\n"
        "- seat_status length exactly 7; values only 0 or 1.\n"
        "- seat_level length exactly 7; values integers only 0..255.\n"
        "- Avoid duplicates unless explicitly asked (replay mode).\n"
    )

    if attack == "replay":
        user_prompt = (
            f"Generate exactly {need} JSONL lines.\n"
            f"Scenario style: REPLAY. Intentionally repeat identical cases.\n"
            f"- About {int(repeat_ratio*100)}% lines should be exactly identical (same door/arrays).\n"
            f"- Remaining lines can be slight variations (change 1-2 indices).\n"
            "Use extreme patterns sometimes (all 0, all 1, all 255, alternating).\n"
            "Return only JSON lines.\n"
        )
    elif attack == "stress":
        user_prompt = (
            f"Generate exactly {need} JSONL lines.\n"
            "Scenario style: BURST STRESS (high-frequency repeated patterns).\n"
            f"- Make burst blocks of repeated identical lines of size about {burst_block}.\n"
            "- Alternate door state across blocks.\n"
            "Use extreme patterns in seat_status/seat_level.\n"
            "Return only JSON lines.\n"
        )
    elif attack == "semantic":
        user_prompt = (
            f"Generate exactly {need} JSONL lines.\n"
            "Scenario style: SEMANTIC ABUSE (valid structure but odd combinations).\n"
            "- Examples: all seat_status=1 while all levels=0; or seat_status=0 with high levels.\n"
            "- Mix a few extreme patterns too.\n"
            "Return only JSON lines.\n"
        )
    else:
        user_prompt = (
            f"Generate exactly {need} JSONL lines.\n"
            "Scenario style: MIXED (replay + burst + semantic abuse).\n"
            "- Include some repeated identical lines.\n"
            "- Include some burst blocks.\n"
            "- Include some semantic-abuse lines.\n"
            "All lines must remain strictly valid by schema.\n"
            "Return only JSON lines.\n"
        )

    return system_prompt, user_prompt


def generate_with_llm(
    api_key: str,
    model: str,
    n_cases: int,
    attack: str,
    repeat_ratio: float,
    burst_block: int,
    max_rounds: int,
) -> List[Dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("openai package not installed. Install with: pip install openai")

    client = OpenAI(api_key=api_key)

    cases: List[Dict[str, Any]] = []
    existing = set()

    round_id = 0
    while len(cases) < n_cases and round_id < max_rounds:
        round_id += 1
        need = n_cases - len(cases)

        system_prompt, user_prompt = build_prompts(attack, need, repeat_ratio, burst_block)

        # Prefer Responses API (your llm_generate_testcases.py uses it)
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        new_cases = parse_jsonl_objects(resp.output_text or "")

        for c in new_cases:
            key = dumps_key(c)
            # In replay mode we WANT duplicates, but still keep at least some diversity.
            if attack != "replay" and key in existing:
                continue
            cases.append(c)
            existing.add(key)
            if len(cases) >= n_cases:
                break

    return cases[:n_cases]


# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attack", default="replay", choices=["replay", "stress", "semantic", "mixed"])
    ap.add_argument("--n", type=int, default=None, help="number of cases (overrides env N_CASES)")
    ap.add_argument("--out", default=None, help="output jsonl path (overrides env OUT_PATH)")

    ap.add_argument("--seed", type=int, default=0, help="random seed for fallback/local generation")
    ap.add_argument("--repeat_ratio", type=float, default=0.7, help="for replay: fraction of identical lines")
    ap.add_argument("--burst_block", type=int, default=10, help="for stress: block size for repeated lines")

    ap.add_argument("--use_llm", action="store_true", help="use OpenAI LLM generation; otherwise local generator")
    ap.add_argument("--max_rounds", type=int, default=6, help="LLM retry rounds if not enough valid lines")
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent

    # Load .env from script directory if available
    if load_dotenv is not None:
        env_path = base_dir / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)

    n_cases = args.n if args.n is not None else int(os.getenv("N_CASES", "30"))
    out_path = Path(args.out if args.out is not None else os.getenv("OUT_PATH", str(base_dir / "testcases_attack.jsonl")))

    attack = args.attack
    repeat_ratio = max(0.0, min(1.0, args.repeat_ratio))
    burst_block = max(1, args.burst_block)

    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    api_key = os.getenv("OPENAI_API_KEY", "")

    cases: List[Dict[str, Any]] = []
    used = "local"

    if args.use_llm:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found. Put it in .env or environment variable.")
        cases = generate_with_llm(
            api_key=api_key,
            model=model,
            n_cases=n_cases,
            attack=attack,
            repeat_ratio=repeat_ratio,
            burst_block=burst_block,
            max_rounds=args.max_rounds,
        )
        used = f"llm:{model}"

        # If LLM didn't reach target, fill with local generator to guarantee output count
        if len(cases) < n_cases:
            rng = random.Random(args.seed)
            fill = build_attack_suite_local(rng, n_cases - len(cases), attack, repeat_ratio, burst_block)
            cases.extend(fill)
            cases = cases[:n_cases]
    else:
        rng = random.Random(args.seed)
        cases = build_attack_suite_local(rng, n_cases, attack, repeat_ratio, burst_block)

    # Final validation + ensure exact count
    final: List[Dict[str, Any]] = []
    for c in cases:
        if is_valid_case(c):
            final.append(c)
        if len(final) >= n_cases:
            break

    if len(final) < n_cases:
        # last resort: pad with a valid extreme
        rng = random.Random(args.seed + 1337)
        while len(final) < n_cases:
            final.append(make_extreme_case(rng))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for c in final[:n_cases]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"[OK] attack={attack} used={used} wrote={n_cases} -> {out_path}")
    if attack == "replay":
        print(f"[INFO] replay repeat_ratio={repeat_ratio}")
    if attack == "stress":
        print(f"[INFO] stress burst_block={burst_block}")


if __name__ == "__main__":
    main()
