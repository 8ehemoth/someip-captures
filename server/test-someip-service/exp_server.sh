#!/usr/bin/env bash
set -euo pipefail

SVC="someip-server.service"

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
  report)
    ./report_status.sh
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs [N]|report}"
    exit 1
    ;;
esac
