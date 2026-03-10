#!/usr/bin/env python3
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "oracle_events.events.jsonl"
last = None

with open(path, "r", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        if obj.get("event") != "port_check":
            continue
        cur = (obj["ports"]["30490"], obj["ports"]["31000"])
        if last is None:
            last = cur
            continue
        if cur != last:
            print(line.strip())
            last = cur
