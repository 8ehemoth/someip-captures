#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import argparse
import subprocess
import hashlib
from datetime import datetime

def jprint(msg: str):
    print(msg, flush=True)

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def append_jsonl(path: str, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def ensure_csv_header(path: str, header: str):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "\n")

def read_proc_status_kb(pid: int):
    vmrss = 0
    vmsize = 0
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    vmrss = int(line.split()[1])
                elif line.startswith("VmSize:"):
                    vmsize = int(line.split()[1])
    except FileNotFoundError:
        pass
    return vmrss, vmsize

def count_fd(pid: int):
    try:
        return len(os.listdir(f"/proc/{pid}/fd"))
    except FileNotFoundError:
        return 0

def read_proc_stat_utime_stime(pid: int):
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="ignore") as f:
            parts = f.read().split()
            if len(parts) >= 16:
                return int(parts[13]), int(parts[14])
    except FileNotFoundError:
        pass
    return 0, 0

def udp_listen_on_port(port: int) -> bool:
    # UDP LISTEN 확인: ss -u -l -n 출력에 :PORT 가 있으면 True
    try:
        out = subprocess.check_output(["ss", "-u", "-l", "-n"], text=True)
        return (f":{port} " in out) or (f":{port}\n" in out)
    except Exception:
        return False

def file_sha1_short(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:10]
    except Exception:
        return "unknown"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="VSOMEIP_CONFIGURATION path (default: vsomeip-server-sd.json)")
    ap.add_argument("--app", default=None, help="VSOMEIP_APPLICATION_NAME (default: playground-service)")
    ap.add_argument("--server-bin", default=None, help="Server binary path (default: ./build/PlaygroundService)")

    # logs
    ap.add_argument("--server-log", default="server.log", help="vsomeip raw log file (append)")
    ap.add_argument("--pidfile", default="server.pid", help="PID file path")
    ap.add_argument("--events-jsonl", default="oracle_events.events.jsonl", help="event-only jsonl")
    ap.add_argument("--proc-csv", default="oracle_events.procstats.csv", help="proc stats csv")

    # intervals
    ap.add_argument("--proc-interval", type=float, default=1.0, help="proc stats interval seconds")
    ap.add_argument("--port-interval", type=float, default=5.0, help="port check interval seconds")

    args = ap.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()

    # 1) LD_LIBRARY_PATH: HOME/usr/lib, HOME/usr/lib64 우선
    home = env.get("HOME", os.path.expanduser("~"))
    ld_paths = [os.path.join(home, "usr", "lib"), os.path.join(home, "usr", "lib64")]
    env["LD_LIBRARY_PATH"] = ":".join(ld_paths) + ":" + env.get("LD_LIBRARY_PATH", "")

    # 2) vsomeip env
    config_path = args.config or env.get("VSOMEIP_CONFIGURATION") or os.path.join(base_dir, "vsomeip-server-sd.json")
    app_name = args.app or env.get("VSOMEIP_APPLICATION_NAME") or "playground-service"
    env["VSOMEIP_CONFIGURATION"] = config_path
    env["VSOMEIP_APPLICATION_NAME"] = app_name

    # 3) server binary
    server_bin = args.server_bin or os.path.join(base_dir, "build", "PlaygroundService")
    if not os.path.exists(server_bin):
        jprint(f"[run_server] ERROR server binary not found: {server_bin}")
        sys.exit(1)

    # 4) paths (상대경로면 base_dir 기준)
    def abspath(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    server_log_path = abspath(args.server_log)
    pidfile_path = abspath(args.pidfile)
    events_path = abspath(args.events_jsonl)
    proc_csv_path = abspath(args.proc_csv)

    # 5) journald용 버전 태그(과거 로그 섞임 방지)
    sha = file_sha1_short(__file__)

    # 6) START 이벤트 기록
    start_evt = {
        "ts": now_iso(),
        "event": "server_start",
        "sha": sha,
        "server_bin": server_bin,
        "vsomeip_config": config_path,
        "app": app_name,
        "ld_library_path_head": ld_paths,
    }
    append_jsonl(events_path, start_evt)
    jprint(f"[run_server] START sha={sha} app={app_name} conf={config_path} bin={server_bin}")

    # 7) 서버 실행
    with open(server_log_path, "a", encoding="utf-8") as lf:
        lf.write(f"\n[{now_iso()}] [INFO] Starting PlaygroundService (sha={sha})\n")
        lf.flush()

        proc = subprocess.Popen(
            [server_bin],
            cwd=base_dir,
            env=env,
            stdout=lf,
            stderr=lf,
            preexec_fn=os.setsid
        )

        # pidfile 기록
        with open(pidfile_path, "w", encoding="utf-8") as pf:
            pf.write(str(proc.pid))
        append_jsonl(events_path, {"ts": now_iso(), "event": "pid_written", "sha": sha, "pid": proc.pid, "pidfile": pidfile_path})
        jprint(f"[run_server] PID sha={sha} pid={proc.pid} pidfile={pidfile_path}")

        # procstats csv 헤더
        ensure_csv_header(proc_csv_path, "ts,sha,pid,vmrss_kb,vmsize_kb,fd_count,utime,stime")

        last_proc = 0.0
        last_port = 0.0

        try:
            while True:
                # 종료 확인
                ret = proc.poll()
                if ret is not None:
                    # EXIT 이벤트
                    exit_evt = {"ts": now_iso(), "event": "server_exit", "sha": sha, "pid": proc.pid, "returncode": ret}
                    append_jsonl(events_path, exit_evt)
                    jprint(f"[run_server] EXIT sha={sha} pid={proc.pid} rc={ret}")

                    lf.write(f"[{now_iso()}] [ERROR] PlaygroundService exited, rc={ret}\n")
                    lf.flush()

                    # pidfile 정리
                    try:
                        os.remove(pidfile_path)
                    except FileNotFoundError:
                        pass

                    # nonzero면 실패로 종료해서 systemd가 재시작하게
                    sys.exit(1 if ret != 0 else 0)

                now = time.time()

                # proc stats (1초 주기)
                if now - last_proc >= max(args.proc_interval, 0.2):
                    vmrss, vmsize = read_proc_status_kb(proc.pid)
                    fd_count = count_fd(proc.pid)
                    utime, stime = read_proc_stat_utime_stime(proc.pid)
                    with open(proc_csv_path, "a", encoding="utf-8") as f:
                        f.write(f"{now_iso()},{sha},{proc.pid},{vmrss},{vmsize},{fd_count},{utime},{stime}\n")
                    last_proc = now

                # port check (5초 주기)
                if now - last_port >= max(args.port_interval, 1.0):
                    ports = {"30490": udp_listen_on_port(30490), "31000": udp_listen_on_port(31000)}
                    append_jsonl(events_path, {
                        "ts": now_iso(),
                        "event": "port_check",
                        "sha": sha,
                        "pid": proc.pid,
                        "ports": ports,
                        "port_ok": bool(ports["30490"] and ports["31000"]),
                    })
                    last_port = now

                time.sleep(0.05)

        except KeyboardInterrupt:
            append_jsonl(events_path, {"ts": now_iso(), "event": "stop_by_user", "sha": sha, "pid": proc.pid})
            jprint(f"[run_server] STOP_BY_USER sha={sha} pid={proc.pid}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            sys.exit(0)

if __name__ == "__main__":
    main()
