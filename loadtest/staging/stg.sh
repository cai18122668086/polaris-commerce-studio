#!/usr/bin/env bash
# staging 开关：stg.sh up [baseline|after] | stop | down | status | logs <svc>
set -u
D=$HOME/work/loadstg
cd "$D"
which_code() { case "${1:-baseline}" in baseline) echo "$D/code-baseline";; after) echo "$D/code-after";; *) echo "$1";; esac; }
c() { sudo -n env STG_CODE="${STG_CODE:-$D/code-baseline}" docker compose --env-file "$D/stg.env" -f "$D/compose.yaml" "$@"; }
case "${1:-status}" in
  up) export STG_CODE=$(which_code "${2:-baseline}"); echo "$STG_CODE" > "$D/current-code"; c up -d --force-recreate --remove-orphans ;;
  stop) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c stop ;;
  down) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c down ;;
  status) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c ps --format '{{.Service}}\t{{.Status}}' ;;
  logs) shift; STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c logs --no-color "$@" ;;
  *) echo "usage: stg.sh up [baseline|after|DIR] | stop | down | status | logs <svc>"; exit 2 ;;
esac
