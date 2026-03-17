#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-someip-server.service}"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
EVENTS="${EVENTS:-$BASE_DIR/oracle_events.events.jsonl}"
PROC_CSV="${PROC_CSV:-$BASE_DIR/oracle_events.procstats.csv}"

N_JOURNAL="${N_JOURNAL:-60}"
N_PROC="${N_PROC:-300}"

line() { printf '%*s\n' "${1:-80}" '' | tr ' ' '-'; }

echo "[report_status] $(date -Iseconds)"
line 80

echo "### 1) systemd status: $SERVICE"
systemctl status "$SERVICE" --no-pager || true

echo
echo "### 2) current PIDs"
echo "MainPID=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)"
echo "- run_server.py:"
pgrep -af "python3 .*run_server.py" || true
echo "- PlaygroundService:"
pgrep -af PlaygroundService || true

echo "--------------------------------------------------------------------------------"
SERVICE="someip-server.service"

since="$(date -d '30 minutes ago' '+%Y-%m-%d %H:%M:%S')"
echo "### 3) journald (since: $since)"
journalctl -u "$SERVICE" --since "$since" -n 200 --no-pager


#echo
#line 80
#echo "### 3) journald (last ${N_JOURNAL} lines)"
#journalctl -u "$SERVICE" -n "$N_JOURNAL" --no-pager || true

echo
line 80
echo "### 4) server events (start/exit recent)"
if [[ -f "$EVENTS" ]]; then
  grep -E '"event":"(server_start|pid_written|server_exit)"' "$EVENTS" | tail -n 20 || true
else
  echo "[WARN] not found: $EVENTS"
fi

echo
line 80
echo "### 5) port_check transitions (server local ports)"
if [[ -f "$EVENTS" ]]; then
  python3 - <<'PY' "$EVENTS"
import json, sys
path=sys.argv[1]
last=None
for line in open(path,"r",encoding="utf-8"):
    try:
        o=json.loads(line)
    except:
        continue
    if o.get("event")!="port_check":
        continue
    cur=(o["ports"].get("30490"), o["ports"].get("31000"))
    if last is None:
        last=cur
        continue
    if cur!=last:
        print(line.strip())
        last=cur
PY
else
  echo "[WARN] not found: $EVENTS"
fi

echo
line 80
echo "### 6) merged client heartbeat (FAIL/HANG only, last 30)"
if [[ -f "$EVENTS" ]]; then
  grep -F '"source":"client_heartbeat"' "$EVENTS" \
  | grep -E '"event":"(heartbeat_fail|hang_suspected|merge_fail)"' \
  | tail -n 30 || true
else
  echo "[WARN] not found: $EVENTS"
fi

echo
line 80
echo "### 7) procstats summary (last ${N_PROC} rows)"
if [[ -f "$PROC_CSV" ]]; then
  tail -n "$N_PROC" "$PROC_CSV" | awk -F',' '
BEGIN{
  minrss=1e18; maxrss=0; minfd=1e18; maxfd=0;
  minut=1e18; maxut=0; minst=1e18; maxst=0;
  first=1;
}
{
  if($1=="ts"){ next }
  ts=$1; sha=$2; pid=$3;
  rss=$4; fd=$6; ut=$7; st=$8;
  if(first){ first=0; fts=ts; }
  lts=ts; lrss=rss; lfd=fd; lut=ut; lst=st; lsha=sha; lpid=pid;
  if(rss<minrss)minrss=rss; if(rss>maxrss)maxrss=rss;
  if(fd<minfd)minfd=fd; if(fd>maxfd)maxfd=fd;
  if(ut<minut)minut=ut; if(ut>maxut)maxut=ut;
  if(st<minst)minst=st; if(st>maxst)maxst=st;
}
END{
  if(first){ print "[ERR] no rows"; exit 0; }
  print "range:", fts, "->", lts;
  print "sha:", lsha, "pid(last):", lpid;
  print "VmRSS(kB):", minrss, "->", maxrss, "(Δ", maxrss-minrss, ")";
  print "FD:", minfd, "->", maxfd, "(Δ", maxfd-minfd, ")";
  print "utime:", minut, "->", maxut, "(Δ", maxut-minut, ")";
  print "stime:", minst, "->", maxst, "(Δ", maxst-minst, ")";
  print "last:", "rss", lrss, "fd", lfd, "ut", lut, "st", lst;
}'
else
  echo "[WARN] not found: $PROC_CSV"
fi

echo
line 80
echo "[report_status] done"
