#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cmd(cmd, timeout=None):
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return p.returncode, p.stdout, p.stderr


def ssh_run(user, host, remote_cmd, timeout=10):
    cmd = ["ssh", f"{user}@{host}", remote_cmd]
    return run_cmd(cmd, timeout=timeout)


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            rows.append(json.loads(s))
    return rows


def write_one_jsonl(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def get_server_health(server_user, server_host, remote_health_cmd, ssh_timeout=10):
    rc, out, err = ssh_run(server_user, server_host, remote_health_cmd, timeout=ssh_timeout)
    if rc != 0:
        return {
            "_ssh_ok": False,
            "_ssh_rc": rc,
            "_ssh_err": err.strip(),
            "server_alive": None,
            "class": "SSH_FAIL",
            "port_ok": None,
            "pid": None,
            "fatal_seen": None,
        }

    out = out.strip()
    try:
        obj = json.loads(out)
        obj["_ssh_ok"] = True
        obj["_ssh_rc"] = 0
        return obj
    except Exception:
        return {
            "_ssh_ok": False,
            "_ssh_rc": 0,
            "_ssh_err": f"health output not json: {out[:200]}",
            "server_alive": None,
            "class": "BAD_HEALTH_JSON",
            "port_ok": None,
            "pid": None,
            "fatal_seen": None,
        }


def get_remote_log_meta(server_user, server_host, remote_log_path, ssh_timeout=10):
    script = f'''
LOG={shlex.quote(remote_log_path)}
if [ -f "$LOG" ]; then
  SIZE=$(stat -c%s "$LOG" 2>/dev/null || echo -1)
  LINES=$(wc -l < "$LOG" 2>/dev/null || echo -1)
  echo '{{"log_exists": true, "log_size": '"$SIZE"', "log_lines": '"$LINES"'}}'
else
  echo '{{"log_exists": false, "log_size": -1, "log_lines": -1}}'
fi
'''.strip()

    remote_cmd = "bash -lc " + shlex.quote(script)
    rc, out, err = ssh_run(server_user, server_host, remote_cmd, timeout=ssh_timeout)

    if rc != 0:
        return {
            "_ssh_ok": False,
            "_ssh_rc": rc,
            "_ssh_err": err.strip(),
            "log_exists": None,
            "log_size": None,
            "log_lines": None,
        }

    out = out.strip()
    try:
        obj = json.loads(out)
        obj["_ssh_ok"] = True
        obj["_ssh_rc"] = 0
        obj["log_size"] = int(obj["log_size"])
        obj["log_lines"] = int(obj["log_lines"])
        return obj
    except Exception:
        return {
            "_ssh_ok": False,
            "_ssh_rc": 0,
            "_ssh_err": f"log meta output not json: {out[:200]}",
            "log_exists": None,
            "log_size": None,
            "log_lines": None,
        }


def parse_case_log(case_log_path):
    rows = []
    if Path(case_log_path).exists():
        with open(case_log_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rows.append(json.loads(s))
                except Exception:
                    pass

    if not rows:
        return {
            "ok": False,
            "t": None,
            "oracle": None,
            "returncode": None,
            "callstatus": None,
            "ping_after": None,
            "server_before": None,
            "server_after": None,
            "callstatus_found": None,
            "callstatus_code": None,
            "ping_after_ok": None,
            "ping_after_returncode": None,
        }

    row = rows[-1]

    result = {
        "ok": row.get("ok"),
        "t": row.get("t", row.get("elapsed", row.get("time_sec"))),
        "oracle": row.get("oracle"),
        "returncode": row.get("returncode"),
        "callstatus": row.get("callstatus"),
        "ping_after": row.get("ping_after"),
        "server_before": row.get("server_before"),
        "server_after": row.get("server_after"),
    }

    cs = result["callstatus"]
    if isinstance(cs, dict):
        result["callstatus_found"] = cs.get("found")
        result["callstatus_code"] = cs.get("code")
    else:
        result["callstatus_found"] = None
        result["callstatus_code"] = None

    pa = result["ping_after"]
    if isinstance(pa, dict):
        result["ping_after_ok"] = pa.get("ok")
        result["ping_after_returncode"] = pa.get("returncode")
    else:
        result["ping_after_ok"] = None
        result["ping_after_returncode"] = None

    return result


def classify(record, baseline_pid=None, slow_ms=800, log_lines_p1=3, log_size_p1=256):
    health = record.get("server_health", {})
    result = record.get("case_result", {})
    log_before = record.get("log_before", {})
    log_after = record.get("log_after", {})

    t_sec = result.get("t")
    t_ms = None
    if isinstance(t_sec, (int, float)):
        t_ms = int(t_sec * 1000)

    pid = health.get("pid")
    pid_changed = False
    if baseline_pid is not None and pid is not None and pid != baseline_pid:
        pid_changed = True

    port_ok = health.get("port_ok")
    alive = health.get("server_alive")
    fatal_seen = health.get("fatal_seen")

    log_delta_size = None
    log_delta_lines = None
    if isinstance(log_before.get("log_size"), int) and isinstance(log_after.get("log_size"), int):
        log_delta_size = log_after["log_size"] - log_before["log_size"]
    if isinstance(log_before.get("log_lines"), int) and isinstance(log_after.get("log_lines"), int):
        log_delta_lines = log_after["log_lines"] - log_before["log_lines"]

    record["derived"] = {
        "t_ms": t_ms,
        "pid_changed": pid_changed,
        "log_delta_size": log_delta_size,
        "log_delta_lines": log_delta_lines,
    }

    # P0: 서버 다운/포트 닫힘/재시작/fatal
    if alive is False or port_ok is False or pid_changed or fatal_seen is True:
        return "P0"

    # P1: 서버는 살아있지만 느리거나 이상 징후
    if t_ms is not None and t_ms >= slow_ms:
        return "P1"

    if log_delta_lines is not None and log_delta_lines >= log_lines_p1:
        return "P1"

    if log_delta_size is not None and log_delta_size >= log_size_p1:
        return "P1"

    if result.get("ok") is False and alive is True and port_ok is True:
        # 클라/입력 드랍 의심
        if result.get("callstatus_found") is False:
            return "P2"
        # 그 외 ok=False는 일단 서버 soft anomaly로 둔다
        return "P1"

    return "NORMAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="입력 케이스 jsonl")
    ap.add_argument("--out", default="oracle_v1_log.jsonl", help="결과 jsonl")
    ap.add_argument("--run_testcases", default="./run_testcases.py")
    ap.add_argument("--server_host", required=True)
    ap.add_argument("--server_user", required=True)
    ap.add_argument(
        "--remote_health_cmd",
        default="python3 /home/server/someip-captures/server/test-someip-service/server_health.py",
    )
    ap.add_argument(
        "--remote_log_path",
        default="/home/server/someip-captures/server/test-someip-service/server.log",
    )
    ap.add_argument("--oracle", default="callstatus")
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--slow_ms", type=int, default=800)
    ap.add_argument("--log_lines_p1", type=int, default=3)
    ap.add_argument("--log_size_p1", type=int, default=256)
    ap.add_argument("--ssh_timeout", type=int, default=10)
    ap.add_argument("--use_run_client_wrapper", action="store_true")
    ap.add_argument("--ping_on_fail", action="store_true")
    args = ap.parse_args()

    cases = read_jsonl(args.jsonl)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    baseline_health = get_server_health(
        args.server_user,
        args.server_host,
        args.remote_health_cmd,
        ssh_timeout=args.ssh_timeout,
    )
    baseline_pid = baseline_health.get("pid")

    normal = p0 = p1 = p2 = 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        with open(out_path, "w", encoding="utf-8") as fout:
            for idx, case in enumerate(cases, start=1):
                case_file = td / f"case_{idx}.jsonl"
                case_log = td / f"case_{idx}_log.jsonl"

                write_one_jsonl(case_file, case)

                log_before = get_remote_log_meta(
                    args.server_user,
                    args.server_host,
                    args.remote_log_path,
                    ssh_timeout=args.ssh_timeout,
                )

                cmd = [
                    sys.executable,
                    args.run_testcases,
                    "--jsonl",
                    str(case_file),
                    "--oracle",
                    args.oracle,
                    "--server_host",
                    args.server_host,
                    "--server_user",
                    args.server_user,
                    "--log",
                    str(case_log),
                    "--delay",
                    str(args.delay),
                    "--timeout",
                    str(args.timeout),
                ]

                if args.use_run_client_wrapper:
                    cmd.append("--use_run_client_wrapper")
                if args.ping_on_fail:
                    cmd.append("--ping_on_fail")

                rc, stdout, stderr = run_cmd(
                    cmd,
                    timeout=max(30, int(args.timeout * 6)),
                )

                case_result = parse_case_log(case_log)
                if case_result.get("returncode") is None:
                    case_result["returncode"] = rc

                server_health = get_server_health(
                    args.server_user,
                    args.server_host,
                    args.remote_health_cmd,
                    ssh_timeout=args.ssh_timeout,
                )

                log_after = get_remote_log_meta(
                    args.server_user,
                    args.server_host,
                    args.remote_log_path,
                    ssh_timeout=args.ssh_timeout,
                )

                rec = {
                    "idx": idx,
                    "input": case,
                    "case_result": case_result,
                    "server_health": server_health,
                    "log_before": log_before,
                    "log_after": log_after,
                    "_runner_rc": rc,
                    "_runner_stdout_tail": stdout.strip()[-300:],
                    "_runner_stderr_tail": stderr.strip()[-300:],
                }

                cls = classify(
                    rec,
                    baseline_pid=baseline_pid,
                    slow_ms=args.slow_ms,
                    log_lines_p1=args.log_lines_p1,
                    log_size_p1=args.log_size_p1,
                )
                rec["class"] = cls

                if cls == "NORMAL":
                    normal += 1
                elif cls == "P0":
                    p0 += 1
                elif cls == "P1":
                    p1 += 1
                elif cls == "P2":
                    p2 += 1

                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fout.flush()

                t_ms = rec["derived"].get("t_ms")
                print(
                    f"[{idx}] class={cls} ok={case_result.get('ok')} "
                    f"t_ms={t_ms} pid={server_health.get('pid')} "
                    f"log_dsize={rec['derived'].get('log_delta_size')} "
                    f"log_dlines={rec['derived'].get('log_delta_lines')}"
                )

    print(f"[DONE] NORMAL={normal} P0={p0} P1={p1} P2={p2} -> {out_path}")


if __name__ == "__main__":
    main()
