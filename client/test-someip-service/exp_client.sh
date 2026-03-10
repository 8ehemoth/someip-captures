#!/usr/bin/env bash
set -euo pipefail

SVC="someip-client-heartbeat.service"

case "${1:-}" in
  start)
    sudo systemctl start "$SVC"
    ;;
  stop)
    sudo systemctl stop "$SVC"
    ;;
  restart)
    sudo systemctl restart "$SVC"
    ;;
  status)
    sudo systemctl status "$SVC" --no-pager
    ;;
  logs)
    journalctl -u "$SVC" -n "${2:-120}" --no-pager
    ;;
  tail)
    tail -n "${2:-50}" ./client_heartbeat.jsonl 2>/dev/null || echo "(no client_heartbeat.jsonl yet)"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs [N]|tail [N]}"
    exit 1
    ;;
esac
