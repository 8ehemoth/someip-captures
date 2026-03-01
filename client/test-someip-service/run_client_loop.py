#!/usr/bin/env python3
import os
import subprocess
import sys
import time

# ======================
# 설정값
# ======================
REPEAT_COUNT = 1000       # 반복 횟수
RUN_DURATION = 3.3       # 한 번 실행 후 유지 시간 (초)
DELAY_BETWEEN = 3.0      # 다음 실행 전 대기 시간 (초)

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    env = os.environ.copy()

    # ======================
    # LD_LIBRARY_PATH 구성
    #  - 반드시 필요한 로컬 wrapper .so 경로 포함
    #  - 기존 user-space 설치 경로 포함
    # ======================
    ld_paths = [
        os.path.join(base_dir, "commonapi-wrappers", "build"),
        os.path.join(base_dir, "commonapi-wrappers", "playground", "lib"),
        os.path.join(env["HOME"], "usr", "lib"),
        os.path.join(env["HOME"], "usr", "lib64"),
    ]

    # 존재하는 디렉토리만 반영
    ld_paths = [p for p in ld_paths if os.path.isdir(p)]

    env["LD_LIBRARY_PATH"] = ":".join(ld_paths) + ":" + env.get("LD_LIBRARY_PATH", "")

    # ======================
    # vSomeIP 설정
    # ======================
    env["VSOMEIP_CONFIGURATION"] = os.path.join(base_dir, "vsomeip-client-sd.json")
    env["VSOMEIP_APPLICATION_NAME"] = "graphql"

    client_bin = os.path.join(base_dir, "build", "PlaygroundClient")

    if not os.path.exists(client_bin):
        print(f"[ERROR] Client binary not found: {client_bin}")
        sys.exit(1)

    print(f"[INFO] Starting client loop: {REPEAT_COUNT} times")
    print(f"[INFO] Client binary: {client_bin}")
    print(f"[INFO] VSOMEIP_CONFIGURATION: {env['VSOMEIP_CONFIGURATION']}")
    print(f"[INFO] DELAY_BETWEEN: {DELAY_BETWEEN}s, RUN_DURATION: {RUN_DURATION}s")

    for i in range(1, REPEAT_COUNT + 1):
        print(f"[INFO] Run {i}/{REPEAT_COUNT}")

        proc = subprocess.Popen(
            [client_bin],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # 실행 유지
        time.sleep(RUN_DURATION)

        # 종료
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

        # 다음 실행 전 대기
        if i != REPEAT_COUNT:
            time.sleep(DELAY_BETWEEN)

    print("[INFO] Client loop finished")

if __name__ == "__main__":
    main()
