#!/usr/bin/env python3
import os
import subprocess
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()

    # 0) commonapi prefix를 가장 앞에 (런타임 모듈/플러그인 로딩 불일치 방지)
    commonapi_prefix = "/usr/local/lib/commonapi"

    # 1) 로컬 wrapper .so 경로
    local_so_paths = [
        os.path.join(base_dir, "commonapi-wrappers", "build"),
        os.path.join(base_dir, "commonapi-wrappers", "playground", "lib"),
    ]

    # 2) user-space 설치 라이브러리 경로
    user_paths = [
        os.path.join(env.get("HOME", ""), "usr", "lib"),
        os.path.join(env.get("HOME", ""), "usr", "lib64"),
    ]

    all_paths = [commonapi_prefix] + local_so_paths + user_paths
    all_paths = [p for p in all_paths if p and os.path.isdir(p)]
    env["LD_LIBRARY_PATH"] = ":".join(all_paths) + ":" + env.get("LD_LIBRARY_PATH", "")

    # 3) CommonAPI 설정: 로컬 commonapi.ini를 강제로 사용 (항상 동일 조건 보장)
    env["COMMONAPI_CONFIG"] = os.path.join(base_dir, "commonapi.ini")

    # 4) vSomeIP 설정
    env["VSOMEIP_CONFIGURATION"] = os.path.join(base_dir, "vsomeip-client-sd.json")
    env["VSOMEIP_APPLICATION_NAME"] = "graphql"

    client_bin = os.path.join(base_dir, "build", "PlaygroundClient")
    if not os.path.exists(client_bin):
        print(f"[ERROR] Client binary not found: {client_bin}")
        return 1

    args = [client_bin] + sys.argv[1:]
    print("[INFO] Starting PlaygroundClient:", " ".join(args))
    # check=False로 두고 rc를 그대로 반환 (heartbeat 판단에 유리)
    p = subprocess.run(args, env=env, check=False)
    return p.returncode

if __name__ == "__main__":
    sys.exit(main())
