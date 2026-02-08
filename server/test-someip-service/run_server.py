#!/usr/bin/env python3
import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 현재 환경변수 복사
    env = os.environ.copy()

    # LD_LIBRARY_PATH 추가
    ld_paths = [
        os.path.join(env["HOME"], "usr", "lib"),
        os.path.join(env["HOME"], "usr", "lib64"),
    ]
    env["LD_LIBRARY_PATH"] = ":".join(ld_paths) + ":" + env.get("LD_LIBRARY_PATH", "")

    # vSomeIP 환경변수
    env["VSOMEIP_CONFIGURATION"] = os.path.join(base_dir, "vsomeip-server-sd.json")
    env["VSOMEIP_APPLICATION_NAME"] = "playground-service"

    # 실행 파일
    server_bin = os.path.join(base_dir, "build", "PlaygroundService")

    if not os.path.exists(server_bin):
        print(f"[ERROR] Server binary not found: {server_bin}")
        sys.exit(1)

    print("[INFO] Starting PlaygroundService (server)")
    subprocess.run([server_bin], env=env, check=True)


if __name__ == "__main__":
    main()
