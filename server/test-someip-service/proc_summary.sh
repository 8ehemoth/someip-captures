#!/usr/bin/env bash
set -euo pipefail
CSV="${1:-oracle_events.procstats.csv}"
N="${2:-300}"  # 최근 N줄(기본 300줄=약 5분)
if [[ ! -f "$CSV" ]]; then
  echo "[ERR] not found: $CSV" >&2
  exit 1
fi

tail -n "$N" "$CSV" | awk -F',' '
BEGIN{
  minrss=1e18; maxrss=0; minfd=1e18; maxfd=0;
  minut=1e18; maxut=0; minst=1e18; maxst=0;
  first=1;
}
{
  ts=$1; sha=$2; pid=$3;
  rss=$4; fd=$6; ut=$7; st=$8;
  if(first){ first=0; fts=ts; fpid=pid; fsha=sha; frss=rss; ffd=fd; fut=ut; fst=st; }
  lts=ts; lpid=pid; lsha=sha; lrss=rss; lfd=fd; lut=ut; lst=st;
  if(rss<minrss)minrss=rss; if(rss>maxrss)maxrss=rss;
  if(fd<minfd)minfd=fd; if(fd>maxfd)maxfd=fd;
  if(ut<minut)minut=ut; if(ut>maxut)maxut=ut;
  if(st<minst)minst=st; if(st>maxst)maxst=st;
}
END{
  if(first){ print "[ERR] no rows"; exit 2; }
  print "range:", fts, "->", lts;
  print "sha:", lsha, "pid:", lpid;
  print "VmRSS(kB):", minrss, "->", maxrss, "(Δ", maxrss-minrss, ")";
  print "FD:", minfd, "->", maxfd, "(Δ", maxfd-minfd, ")";
  print "utime:", minut, "->", maxut, "(Δ", maxut-minut, ")";
  print "stime:", minst, "->", maxst, "(Δ", maxst-minst, ")";
  print "last:", "rss", lrss, "fd", lfd, "ut", lut, "st", lst;
}'
