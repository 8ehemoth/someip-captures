#!/usr/bin/env python3
import os
import json
import time
import argparse
import subprocess

def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

def read_pid(pidfile: str):
    try:
        with open(pidfile, "r", encoding="utf-8") as f:
            s = f.read().strip()
        digits = ""
        for ch in s:
            if ch.isdigit():
                digits += ch
            else:
                break
        return int(digits) if digits else None
    except Exception:
        return None

def ss_ports_ok(ports):
    try:
        p = subprocess.run(
            ["ss", "-uapn"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2.0,
        )
        out = p.stdout
    except Exception as e:
        return False, f"ss_failed:{e}"

    ok = True
    missing = []
    for port in ports:
        if f":{port}" not in out:
            ok = False
            missing.append(port)
    return ok, {"missing": missing}

def tail_file(path: str, n: int):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).rstrip("\n")
    except Exception as e:
        return f"[tail_error] {e}"

def read_oracle_status(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pidfile", default="server.pid")
    ap.add_argument("--log", default="server.log")
    ap.add_argument("--ports", default="30490,31000")
    ap.add_argument("--tail", type=int, default=15)
    ap.add_argument("--oracle", default="oracle_status.json")
    args = ap.parse_args()

    ports = []
    for x in args.ports.split(","):
        x = x.strip()
        if x:
            ports.append(int(x))

    # 1) oracle_status.json 우선
    oracle = read_oracle_status(args.oracle)
    if isinstance(oracle, dict) and ("alive" in oracle or "class" in oracle):
        rec = {
            "ts": round(time.time(), 3),
            "source": "oracle_status",
            "oracle_path": args.oracle,
            "server_alive": bool(oracle.get("alive", False)),
            "class": oracle.get("class"),
            "pid": oracle.get("pid"),
            "exit_code": oracle.get("exit_code"),
            "port_ok": oracle.get("port_ok"),
            "ports": oracle.get("ports"),
            "fatal_seen": oracle.get("fatal_seen"),
            "fatal_keyword": oracle.get("fatal_keyword"),
            "log_path": oracle.get("log_path"),
        }
        print(json.dumps(rec, ensure_ascii=False))
        return

    # 2) fallback: pidfile + ss + log_tail
    pid = read_pid(args.pidfile)
    alive = pid_alive(pid) if pid is not None else False
    ports_ok, ports_detail = ss_ports_ok(ports)
    log_tail = tail_file(args.log, args.tail)

    rec = {
        "ts": round(time.time(), 3),
        "source": "pidfile",
        "pidfile": args.pidfile,
        "pid": pid,
        "server_alive": bool(alive),
        "ports": ports,
        "ports_ok": bool(ports_ok),
        "ports_detail": ports_detail,
        "log": args.log,
        "log_tail": log_tail,
    }
    print(json.dumps(rec, ensure_ascii=False))

if __name__ == "__main__":
    main()
