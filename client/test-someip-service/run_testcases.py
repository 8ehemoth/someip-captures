#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path


def list_to_csv(arr):
    return ",".join(str(x) for x in arr)


def ssh_server_health(host, user, remote_cmd, timeout_sec=3.0):
    if not host:
        return {"_ok": False, "_err": "server_host_not_set"}

    target = f"{user}@{host}" if user else host
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=2",
        target,
        remote_cmd,
    ]
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
        )
        dt = time.time() - t0
        out = (p.stdout or "").strip()
        if p.returncode != 0:
            return {"_ok": False, "_err": f"ssh_rc={p.returncode}", "_out": out, "_elapsed": round(dt, 3)}

        try:
            obj = json.loads(out.splitlines()[-1])
            obj["_ok"] = True
            obj["_elapsed"] = round(dt, 3)
            return obj
        except Exception as e:
            return {"_ok": False, "_err": f"json_parse_fail:{e}", "_out": out, "_elapsed": round(dt, 3)}

    except subprocess.TimeoutExpired:
        dt = time.time() - t0
        return {"_ok": False, "_err": "ssh_timeout", "_elapsed": round(dt, 3)}
    except Exception as e:
        dt = time.time() - t0
        return {"_ok": False, "_err": f"ssh_exception:{e}", "_elapsed": round(dt, 3)}


def extract_callstatus(output_text: str):
    if not output_text:
        return {"found": False}

    lines = output_text.splitlines()
    cs = []
    for ln in lines:
        if "CallStatus=" in ln:
            try:
                _, right = ln.split("CallStatus=", 1)
                val_str = ""
                for ch in right.strip():
                    if ch.isdigit() or ch == "-":
                        val_str += ch
                    else:
                        break
                if val_str:
                    cs.append(int(val_str))
            except Exception:
                continue

    if not cs:
        return {"found": False}
    return {
        "found": True,
        "values": cs,
        "all_zero": all(v == 0 for v in cs),
        "any_nonzero": any(v != 0 for v in cs),
    }


def do_ping(client_cmd_prefix, env, ping_timeout_ms: int, proc_timeout_sec: float):
    cmd = client_cmd_prefix + ["--ping", "--ping_timeout_ms", str(ping_timeout_ms)]
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=proc_timeout_sec,
        )
        dt = time.time() - t0
        out_tail = "\n".join((p.stdout or "").splitlines()[-25:])
        return {
            "_ok": True,
            "returncode": p.returncode,
            "elapsed_sec": round(dt, 3),
            "cmd": cmd,
            "output_tail": out_tail,
        }
    except subprocess.TimeoutExpired as e:
        dt = time.time() - t0
        out = ""
        if getattr(e, "stdout", None):
            out = e.stdout
        elif getattr(e, "output", None):
            out = e.output
        out_tail = "\n".join((out or "").splitlines()[-25:])
        return {
            "_ok": False,
            "_err": "ping_timeout",
            "elapsed_sec": round(dt, 3),
            "cmd": cmd,
            "output_tail": out_tail,
        }
    except Exception as e:
        dt = time.time() - t0
        return {
            "_ok": False,
            "_err": f"ping_exception:{e}",
            "elapsed_sec": round(dt, 3),
            "cmd": cmd,
        }


def build_client_env(base: Path):
    env = os.environ.copy()

    local_so_paths = [
        base / "commonapi-wrappers" / "build",
        base / "commonapi-wrappers" / "playground" / "lib",
    ]
    user_paths = [
        Path(env.get("HOME", "")) / "usr" / "lib",
        Path(env.get("HOME", "")) / "usr" / "lib64",
    ]

    all_paths = [str(p) for p in (local_so_paths + user_paths) if p.is_dir()]
    old_ld = env.get("LD_LIBRARY_PATH", "")
    if all_paths:
        env["LD_LIBRARY_PATH"] = ":".join(all_paths + ([old_ld] if old_ld else []))
    else:
        env["LD_LIBRARY_PATH"] = old_ld

    env.setdefault("VSOMEIP_APPLICATION_NAME", "graphql")
    env.setdefault("VSOMEIP_CONFIGURATION", str(base / "vsomeip-client-sd.json"))
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="testcases.jsonl")
    ap.add_argument("--client", default="./build/PlaygroundClient")
    ap.add_argument("--delay", type=float, default=0.2, help="sleep seconds between cases")
    ap.add_argument("--timeout", type=float, default=10.0, help="per case timeout seconds")
    ap.add_argument("--log", default="replay_log.jsonl")
    ap.add_argument("--stop_on_fail", action="store_true")

    ap.add_argument("--server_host", default="", help="server VM IP/host (e.g., 192.168.40.134)")
    ap.add_argument("--server_user", default="server", help="ssh user for server VM")
    ap.add_argument(
        "--server_health_cmd",
        default="cd ~/someip-captures/server/test-someip-service && python3 server_health.py",
        help="remote command to run on server via ssh",
    )
    ap.add_argument("--server_check_every", type=int, default=1, help="check server every N cases (1=every case)")
    ap.add_argument("--oracle", default="returncode", choices=["returncode", "callstatus"], help="oracle mode")

    ap.add_argument(
        "--ping_on_fail",
        action="store_true",
        help="if a case fails/timeout, run an extra --ping to check server responsiveness",
    )
    ap.add_argument("--ping_timeout_ms", type=int, default=1000, help="PlaygroundClient --ping_timeout_ms value")
    ap.add_argument("--ping_proc_timeout", type=float, default=2.0, help="timeout seconds for the ping subprocess")

    ap.add_argument(
        "--use_run_client_wrapper",
        action="store_true",
        help="run via ./run_client.py to ensure identical env as manual run",
    )

    args = ap.parse_args()

    base = Path.cwd()
    jsonl_path = base / args.jsonl
    if not jsonl_path.exists():
        print(f"[ERR] jsonl not found: {jsonl_path}", file=sys.stderr)
        return 2

    env = build_client_env(base)

    if args.use_run_client_wrapper:
        wrapper = base / "run_client.py"
        if not wrapper.exists():
            print(f"[ERR] run_client.py not found: {wrapper}", file=sys.stderr)
            return 4
        client_cmd_prefix = [sys.executable, str(wrapper)]
    else:
        client_path = base / args.client
        if not client_path.exists():
            print(f"[ERR] client not found: {client_path}", file=sys.stderr)
            return 3
        client_cmd_prefix = [str(client_path)]

    ok = 0
    fail = 0
    last_server_health = None

    with open(jsonl_path, "r", encoding="utf-8") as f_in, open(args.log, "w", encoding="utf-8") as f_log:
        for idx, line in enumerate(f_in, 1):
            line = line.strip()
            if not line:
                continue

            # 1) JSON 파싱 + CLI 인자 준비
            try:
                tc = json.loads(line)
                door = tc.get("door")
                seat_status = tc.get("seat_status")
                seat_level = tc.get("seat_level")

                if door is None or seat_status is None or seat_level is None:
                    raise ValueError("missing one of keys: door/seat_status/seat_level")

                ss = list_to_csv(seat_status)
                sl = list_to_csv(seat_level)

            except Exception as e:
                fail += 1
                rec = {"idx": idx, "status": "invalid_json", "error": str(e), "line": line}
                f_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"[{idx}] INVALID_JSON error={e}")
                if args.stop_on_fail:
                    break
                time.sleep(args.delay)
                continue

            # 2) 서버 상태 pre-check
            server_before = None
            do_check = (
                args.server_host != ""
                and args.server_check_every > 0
                and ((idx - 1) % args.server_check_every == 0)
            )
            if do_check:
                server_before = ssh_server_health(args.server_host, args.server_user, args.server_health_cmd)
                last_server_health = server_before

                if server_before.get("_ok") and (not server_before.get("server_alive", True)):
                    rec = {
                        "idx": idx,
                        "status": "server_down_before_case",
                        "door": door,
                        "seat_status": seat_status,
                        "seat_level": seat_level,
                        "server_before": server_before,
                        "ok": False,
                    }
                    f_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    print(f"[{idx}] SERVER DOWN before case -> stop")
                    break

            cmd = client_cmd_prefix + [
                "--count", "1",
                "--delay", "0",
                "--door", str(door),
                "--seat_status", ss,
                "--seat_level", sl,
            ]

            # 3) 케이스 실행
            t0 = time.time()
            try:
                p = subprocess.run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=args.timeout,
                )
                dt = time.time() - t0
                out_text = p.stdout or ""

                # 4) oracle 판정
                if args.oracle == "returncode":
                    success = (p.returncode == 0)
                    oracle_detail = {"mode": "returncode", "returncode": p.returncode}
                else:
                    cs = extract_callstatus(out_text)
                    success = bool(cs.get("found") and cs.get("all_zero"))
                    oracle_detail = {"mode": "callstatus", "callstatus": cs, "returncode": p.returncode}

                if success:
                    ok += 1
                else:
                    fail += 1

                # 5) 실패 시 ping_after 추가 기록
                ping_after = None
                if args.ping_on_fail and (not success):
                    ping_after = do_ping(client_cmd_prefix, env, args.ping_timeout_ms, args.ping_proc_timeout)

                # 6) 서버 상태 post-check
                server_after = None
                if do_check:
                    server_after = ssh_server_health(args.server_host, args.server_user, args.server_health_cmd)
                    last_server_health = server_after

                rec = {
                    "idx": idx,
                    "elapsed_sec": round(dt, 3),
                    "door": door,
                    "seat_status": seat_status,
                    "seat_level": seat_level,
                    "ok": bool(success),
                    "oracle": oracle_detail,
                    "output_tail": "\n".join(out_text.splitlines()[-25:]),
                    "cmd": cmd,
                }
                if server_before is not None:
                    rec["server_before"] = server_before
                if server_after is not None:
                    rec["server_after"] = server_after
                if ping_after is not None:
                    rec["ping_after"] = ping_after

                f_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"[{idx}] ok={success} t={dt:.2f}s oracle={args.oracle}")

                if (not success) and args.stop_on_fail:
                    break

            except subprocess.TimeoutExpired as e:
                dt = time.time() - t0
                fail += 1

                out = ""
                if getattr(e, "stdout", None):
                    out = e.stdout
                elif getattr(e, "output", None):
                    out = e.output

                server_after = None
                if do_check:
                    server_after = ssh_server_health(args.server_host, args.server_user, args.server_health_cmd)
                    last_server_health = server_after

                ping_after = None
                if args.ping_on_fail:
                    ping_after = do_ping(client_cmd_prefix, env, args.ping_timeout_ms, args.ping_proc_timeout)

                rec = {
                    "idx": idx,
                    "status": "timeout",
                    "elapsed_sec": round(dt, 3),
                    "door": door,
                    "seat_status": seat_status,
                    "seat_level": seat_level,
                    "ok": False,
                    "oracle": {"mode": args.oracle},
                    "cmd": cmd,
                    "output_tail": "\n".join((out or "").splitlines()[-25:]),
                }
                if server_before is not None:
                    rec["server_before"] = server_before
                if server_after is not None:
                    rec["server_after"] = server_after
                if ping_after is not None:
                    rec["ping_after"] = ping_after

                f_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"[{idx}] TIMEOUT t={dt:.2f}s oracle={args.oracle}")

                if args.stop_on_fail:
                    break

            time.sleep(args.delay)

    print(f"[DONE] ok={ok} fail={fail} log={args.log} oracle={args.oracle}")
    if last_server_health is not None:
        print("[LAST_SERVER_HEALTH]", json.dumps(last_server_health, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
