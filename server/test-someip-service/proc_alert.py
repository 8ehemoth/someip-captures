#!/usr/bin/env python3
import sys, csv

csv_path = sys.argv[1] if len(sys.argv) > 1 else "oracle_events.procstats.csv"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 300  # 최근 n줄(기본 5분)

# 임계값(너 상황에 맞게 조정 가능)
RSS_DELTA_KB = int(sys.argv[3]) if len(sys.argv) > 3 else 20000  # 20MB
FD_DELTA = int(sys.argv[4]) if len(sys.argv) > 4 else 50
CPU_TICK_DELTA = int(sys.argv[5]) if len(sys.argv) > 5 else 2000

rows = []
with open(csv_path, newline="", encoding="utf-8") as f:
    reader = csv.reader(f)
    for r in reader:
        if not r or r[0] == "ts":
            continue
        rows.append(r)

if not rows:
    print("[ERR] no data rows")
    sys.exit(2)

rows = rows[-n:] if len(rows) > n else rows

def to_int(x, default=0):
    try: return int(x)
    except: return default

first = rows[0]
last = rows[-1]

fts, fsha, fpid = first[0], first[1], first[2]
lts, lsha, lpid = last[0], last[1], last[2]

frss = to_int(first[3]); lrss = to_int(last[3])
ffd  = to_int(first[5]); lfd  = to_int(last[5])
fut  = to_int(first[6]); lut  = to_int(last[6])
fst  = to_int(first[7]); lst  = to_int(last[7])

drss = lrss - frss
dfd = lfd - ffd
dcpu = (lut + lst) - (fut + fst)

print(f"range {fts} -> {lts} | sha={lsha} pid={lpid}")
print(f"Δrss_kb={drss} (threshold {RSS_DELTA_KB}), Δfd={dfd} (threshold {FD_DELTA}), Δcpu_ticks={dcpu} (threshold {CPU_TICK_DELTA})")

alerts = []
if drss > RSS_DELTA_KB:
    alerts.append(f"[ALERT] VmRSS increased by {drss} kB")
if dfd > FD_DELTA:
    alerts.append(f"[ALERT] FD count increased by {dfd}")
if dcpu > CPU_TICK_DELTA:
    alerts.append(f"[ALERT] CPU ticks increased by {dcpu}")

if alerts:
    for a in alerts:
        print(a)
    sys.exit(1)
else:
    print("[OK] no anomaly by thresholds")
    sys.exit(0)
