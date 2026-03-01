#!/usr/bin/env python3
import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()

    # 로컬 wrapper .so 경로
    local_so_paths = [
        os.path.join(base_dir, "commonapi-wrappers", "build"),
        os.path.join(base_dir, "commonapi-wrappers", "playground", "lib"),
    ]

    # 기존 user-space 설치 라이브러리 경로
    user_paths = [
        os.path.join(env["HOME"], "usr", "lib"),
        os.path.join(env["HOME"], "usr", "lib64"),
    ]

    all_paths = [p for p in (local_so_paths + user_paths) if os.path.isdir(p)]
    env["LD_LIBRARY_PATH"] = ":".join(all_paths) + ":" + env.get("LD_LIBRARY_PATH", "")

    # vSomeIP 설정
    env["VSOMEIP_CONFIGURATION"] = os.path.join(base_dir, "vsomeip-client-sd.json")
    env["VSOMEIP_APPLICATION_NAME"] = "graphql"

    # 중요: COMMONAPI_CONFIG 강제하지 않음 -> /etc/commonapi.ini 사용
    client_bin = os.path.join(base_dir, "build", "PlaygroundClient")
    if not os.path.exists(client_bin):
        print(f"[ERROR] Client binary not found: {client_bin}")
        sys.exit(1)

    args = [client_bin] + sys.argv[1:]
    print("[INFO] Starting PlaygroundClient:", " ".join(args))
    subprocess.run(args, env=env, check=True)

if __name__ == "__main__":
    main()
