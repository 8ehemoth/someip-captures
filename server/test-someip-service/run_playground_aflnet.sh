#!/usr/bin/env bash
set -e

export LD_LIBRARY_PATH=/home/server/usr/lib:/home/server/someip-captures/server/test-someip-service/commonapi-wrappers/playground/lib:$LD_LIBRARY_PATH
export VSOMEIP_CONFIGURATION=/home/server/someip-captures/server/test-someip-service/vsomeip-server-sd.json
export VSOMEIP_APPLICATION_NAME=playground-service

exec /home/server/someip-captures/server/test-someip-service/build-aflnet/PlaygroundService
